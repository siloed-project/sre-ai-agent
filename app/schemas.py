from typing import TypedDict


class ToolResult(TypedDict):
    ok: bool
    items: list[dict]
    error: str | None
