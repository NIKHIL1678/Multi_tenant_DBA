"""What ZipZy may ask this connector to do: a fixed list of read-only tools.

ZipZy has its own allow-list too; a request runs only if the tool is on BOTH lists, and only
against a database that is in this server's connector.yaml. There is no tool that runs SQL
sent from outside.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from zipzy_connector.collectors import CollectorError, collect
from zipzy_connector.config import ConnectorFile
from zipzy_connector.engines import probe


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Tool = Callable[[ConnectorFile, dict[str, Any]], Awaitable[dict[str, Any]]]


def _database(config: ConnectorFile, args: dict[str, Any]) -> Any:
    name = args.get("datasource")
    for db in config.databases:
        if db.name == name:
            return db
    raise ToolError("unknown_datasource", f"'{name}' is not in this connector's settings file")


async def tool_probe(config: ConnectorFile, args: dict[str, Any]) -> dict[str, Any]:
    """Test one database now: reachable, version, capabilities (and why it failed)."""
    result = await probe(_database(config, args))
    return {**result.report(), "error": result.error}


def _collector(name: str) -> Tool:
    async def run(config: ConnectorFile, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return await collect(name, _database(config, args))
        except CollectorError as exc:
            raise ToolError(exc.code, exc.message) from None

    run.__doc__ = f"Run the read-only '{name}' collector on one database."
    return run


TOOLS: dict[str, Tool] = {
    "probe": tool_probe,
    "health": _collector("health"),
    "table_stats": _collector("table_stats"),
    "indexes": _collector("indexes"),
}


async def run_tool(config: ConnectorFile, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError("unknown_tool", f"this connector version does not offer '{name}'")
    return await tool(config, args)
