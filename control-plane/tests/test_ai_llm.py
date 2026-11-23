"""The Groq client, against a fake Groq API (httpx MockTransport): what is sent, what is
accepted, and how failures are retried or reported. No network."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.ai.llm import AIUnavailableError, GroqLLM
from app.ai.outputs import AnswerOut, PlanOut, SpecialistOut
from app.ai.strict import strict_schema
from app.core.config import Settings

Reply = Callable[[dict[str, Any]], httpx.Response]


def settings() -> Settings:
    return Settings(
        jwt_secret=SecretStr("x" * 40),
        groq_api_key=SecretStr("gsk_test"),
        ai_model="openai/gpt-oss-120b",
        ai_fallback_model="openai/gpt-oss-20b",
    )


def completion(content: str, *, prompt: int = 120, completion_tokens: int = 40) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "openai/gpt-oss-120b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt + completion_tokens,
            },
        },
    )


def error(status: int, message: str, code: str | None = None) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": message, "type": "invalid_request_error", "code": code}}
    )


class FakeGroq:
    def __init__(self, *replies: Reply | httpx.Response) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(
            {"url": str(request.url), "auth": request.headers["authorization"], **body}
        )
        reply = self.replies.pop(0)
        return reply(body) if callable(reply) else reply

    def llm(self) -> GroqLLM:
        return GroqLLM(settings(), httpx.AsyncClient(transport=httpx.MockTransport(self)))


ANSWER = json.dumps({"answer": "All good.", "follow_ups": ["Show slow queries"]})


async def test_sends_a_strict_schema_and_reads_the_answer() -> None:
    groq = FakeGroq(completion(ANSWER))
    value, usage = await groq.llm().structured(
        system="You are a DBA.", user="How is it?", output=AnswerOut, name="answer"
    )
    assert value == AnswerOut(answer="All good.", follow_ups=["Show slow queries"])
    assert (usage.input_tokens, usage.output_tokens, usage.models) == (
        120,
        40,
        ["openai/gpt-oss-120b"],
    )

    sent = groq.requests[0]
    assert sent["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert sent["auth"] == "Bearer gsk_test"
    assert sent["model"] == "openai/gpt-oss-120b" and sent["reasoning_effort"] == "medium"
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    fmt = sent["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["name"] == "answer"
    assert fmt["json_schema"]["schema"] == strict_schema(AnswerOut)


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for v in node.values():
            found.extend(_objects(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_objects(v))
    return found


def _keywords(node: Any) -> set[str]:
    """Schema keywords used anywhere (property names are not keywords)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("properties", "$defs"):
                for sub in value.values():
                    found |= _keywords(sub)
            else:
                found.add(key)
                found |= _keywords(value)
    elif isinstance(node, list):
        for v in node:
            found |= _keywords(v)
    return found


@pytest.mark.parametrize("model", [PlanOut, SpecialistOut, AnswerOut])
def test_schemas_follow_groq_strict_rules(model: type) -> None:
    schema = strict_schema(model)
    objects = _objects(schema)
    assert objects, "has objects"
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"]), "every property required"
    assert not _keywords(schema) & {
        "maxLength",
        "maxItems",
        "pattern",
        "default",
        "format",
        "title",
    }
    assert "title" in strict_schema(SpecialistOut)["$defs"]["FindingOut"]["properties"], (
        "a field named title is kept; only the schema keyword is dropped"
    )
    # Optional fields stay possible as a union with null.
    assert '"type": "null"' in json.dumps(strict_schema(PlanOut))


async def test_rate_limit_then_fallback_model() -> None:
    groq = FakeGroq(
        error(429, "Rate limit reached"),
        error(503, "Service unavailable"),
        completion(ANSWER, prompt=10, completion_tokens=5),
    )
    value, usage = await groq.llm().structured(system="s", user="u", output=AnswerOut, name="a")
    assert value.answer == "All good."
    assert [r["model"] for r in groq.requests] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    assert usage.models == ["openai/gpt-oss-20b"] and usage.input_tokens == 10


async def test_invalid_answers_are_retried_and_counted() -> None:
    too_long = json.dumps({"answer": "x" * 5000, "follow_ups": []})
    groq = FakeGroq(
        completion("not json"),
        error(400, "Generated JSON does not match the schema", "json_validate_failed"),
        completion(too_long),
    )
    with pytest.raises(AIUnavailableError, match="expected format"):
        await groq.llm().structured(system="s", user="u", output=AnswerOut, name="a")
    assert len(groq.requests) == 3


async def test_extra_fields_are_refused() -> None:
    sneaky = json.dumps({"answer": "ok", "follow_ups": [], "run_sql": "DROP TABLE t"})
    groq = FakeGroq(completion(sneaky), completion(sneaky), completion(sneaky))
    with pytest.raises(AIUnavailableError):
        await groq.llm().structured(system="s", user="u", output=AnswerOut, name="a")


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (error(401, "Invalid API Key"), "key was refused"),
        (error(404, "The model does not exist"), "does not offer"),
        (error(400, "messages: bad"), "refused the request"),
    ],
)
async def test_hopeless_errors_stop_at_once(reply: httpx.Response, message: str) -> None:
    groq = FakeGroq(reply)
    with pytest.raises(AIUnavailableError, match=message):
        await groq.llm().structured(system="s", user="u", output=AnswerOut, name="a")
    assert len(groq.requests) == 1


async def test_a_think_block_before_the_json_is_ignored() -> None:
    groq = FakeGroq(completion("<think>reasoning…</think>\n" + ANSWER))
    value, _ = await groq.llm().structured(system="s", user="u", output=AnswerOut, name="a")
    assert value.answer == "All good."
