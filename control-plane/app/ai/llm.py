"""The language model behind the agents: Groq through LangChain's ChatGroq.

One method, `structured`: a system prompt, a user message and an output model in; a validated
instance of that model out. The answer is requested in Groq's strict JSON-schema mode and then
validated again with Pydantic (limits, enums, no extra fields).

Failures (in this order of attempts: main model, main model again, fallback model):
- rate limit, server error, connection trouble, timeout, malformed or invalid JSON -> next try
- refused key, unknown model, other bad requests -> stop at once (retrying cannot help)
When every attempt fails, AIUnavailableError says why in words a person can act on.
Tokens of every attempt that got an answer are counted.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import groq
import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from app.ai.strict import response_format
from app.core.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


class AIUnavailableError(Exception):
    """No usable answer from the model; the message is safe to show."""


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    models: list[str] = field(default_factory=list)  # models that answered

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.models.extend(m for m in other.models if m not in self.models)


class LLM(Protocol):
    async def structured(
        self, *, system: str, user: str, output: type[T], name: str
    ) -> tuple[T, Usage]: ...


_RETRY = (
    groq.RateLimitError,
    groq.InternalServerError,
    groq.APIConnectionError,  # includes APITimeoutError
    TimeoutError,
)


class GroqLLM:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http_client
        self._clients: dict[str, ChatGroq] = {}

    def _chat(self, model: str) -> ChatGroq:
        if model not in self._clients:
            s = self._settings
            self._clients[model] = ChatGroq(
                model_name=model,
                api_key=s.groq_api_key,
                temperature=0.2,
                max_tokens=s.ai_max_output_tokens,
                reasoning_effort=s.ai_reasoning_effort,
                timeout=s.ai_call_timeout_seconds,
                max_retries=0,  # retries and fallback are decided here
                http_async_client=self._http,
            )
        return self._clients[model]

    async def structured(
        self, *, system: str, user: str, output: type[T], name: str
    ) -> tuple[T, Usage]:
        s = self._settings
        usage = Usage()
        fmt = response_format(output, name)
        messages = [SystemMessage(system), HumanMessage(user)]
        last = "The AI service did not answer."
        for model in (s.ai_model, s.ai_model, s.ai_fallback_model):
            try:
                reply = await asyncio.wait_for(
                    self._chat(model).ainvoke(messages, response_format=fmt),
                    timeout=s.ai_call_timeout_seconds + 5,
                )
            except groq.AuthenticationError:
                raise AIUnavailableError("The Groq API key was refused.") from None
            except groq.PermissionDeniedError:
                raise AIUnavailableError("The Groq API key may not use this model.") from None
            except groq.NotFoundError:
                raise AIUnavailableError(f"Groq does not offer the model {model}.") from None
            except groq.BadRequestError as exc:
                if "json_validate_failed" not in str(exc):
                    logger.warning("groq bad request", extra={"model": model, "call": name})
                    raise AIUnavailableError("The AI service refused the request.") from None
                last = "The AI answer did not match the expected format."
                continue
            except _RETRY as exc:
                last = (
                    "The AI service is busy; try again in a minute."
                    if isinstance(exc, groq.RateLimitError)
                    else "The AI service could not be reached."
                )
                logger.info("groq retry", extra={"model": model, "call": name, "error": repr(exc)})
                continue

            meta: dict[str, Any] = dict(reply.usage_metadata or {})
            usage.add(Usage(meta.get("input_tokens", 0), meta.get("output_tokens", 0), [model]))
            text = reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
            try:
                return output.model_validate_json(_THINK.sub("", text)), usage
            except ValidationError:
                last = "The AI answer did not match the expected format."
                logger.info("groq invalid answer", extra={"model": model, "call": name})
                continue
        raise AIUnavailableError(last)
