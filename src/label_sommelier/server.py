"""MCP Server for Label Sommelier."""
import asyncio
import logging
import traceback
from typing import Any, Sequence

from mcp.server import Server
from mcp.types import TextContent, ImageContent, EmbeddedResource, Tool

from . import db
from .toolhandler import ToolHandler
from .tools_wine import (
    ScanWineLabelHandler,
    MatchPreferenceHandler,
    GetWineDetailHandler,
    SavePreferenceHandler,
    GetHistoryHandler,
    RecommendWineHandler,
)
from .tools_kakao import FindWineShopsHandler
from .tools_search import SearchWineHandler
from .tools_social import ShareTastingNoteHandler, GetPreferenceStatsHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("label-sommelier")

app = Server("label-sommelier")

_tool_handlers: dict[str, ToolHandler] = {}


def _register(handler: ToolHandler) -> None:
    _tool_handlers[handler.name] = handler


# 모든 툴 등록
_register(ScanWineLabelHandler())
_register(MatchPreferenceHandler())
_register(GetWineDetailHandler())
_register(SavePreferenceHandler())
_register(GetHistoryHandler())
_register(RecommendWineHandler())
_register(FindWineShopsHandler())
_register(SearchWineHandler())
_register(ShareTastingNoteHandler())
_register(GetPreferenceStatsHandler())


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [h.get_tool_description() for h in _tool_handlers.values()]


@app.call_tool()
async def call_tool(
    name: str, arguments: Any
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    try:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")
        handler = _tool_handlers.get(name)
        if not handler:
            raise ValueError(f"Unknown tool: {name}")
        # run_tool은 동기 함수 → 스레드 풀에서 실행
        return await asyncio.to_thread(handler.run_tool, arguments)
    except Exception as e:
        logger.error(traceback.format_exc())
        raise RuntimeError(f"Tool error ({name}): {e}") from e


async def main() -> None:
    db.init_db()
    logger.info("Label Sommelier MCP server starting (10 tools)")

    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
