from abc import ABC, abstractmethod
from typing import Any, Sequence

from mcp.types import TextContent, Tool


class ToolHandler(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_tool_description(self) -> Tool:
        pass

    @abstractmethod
    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        pass
