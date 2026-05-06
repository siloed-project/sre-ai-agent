from app.schemas import ToolResult


def test_tool_result_ok_shape():
    result: ToolResult = {"ok": True, "items": [{"name": "pod-a"}], "error": None}
    assert result["ok"] is True
    assert result["items"] == [{"name": "pod-a"}]
    assert result["error"] is None


def test_tool_result_error_shape():
    result: ToolResult = {"ok": False, "items": [], "error": "connection refused"}
    assert result["ok"] is False
    assert result["items"] == []
    assert result["error"] == "connection refused"
