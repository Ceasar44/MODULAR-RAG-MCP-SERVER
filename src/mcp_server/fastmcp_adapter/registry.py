"""Single registration point for the three public RAG tools."""

from fastmcp import FastMCP

from .tools.get_document_summary import get_document_summary
from .tools.list_collections import list_collections
from .tools.query_knowledge_hub import query_knowledge_hub

_TOOLS = (query_knowledge_hub, list_collections, get_document_summary)


def get_registered_tool_names() -> tuple[str, ...]:
    return tuple(tool.__name__ for tool in _TOOLS)


def register_tools(mcp: FastMCP) -> None:
    for tool in _TOOLS:
        mcp.tool(name=tool.__name__, annotations={"readOnlyHint": True})(tool)
