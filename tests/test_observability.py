import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.observability import SREAgentCallbackHandler, make_callbacks


def _make_llm_result(input_tokens: int = 0, output_tokens: int = 0):
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens}
    )
    gen = SimpleNamespace(message=msg)
    return SimpleNamespace(generations=[[gen]])


class TestSREAgentCallbackHandler:
    def test_on_tool_end_increments_counter(self):
        h = SREAgentCallbackHandler()
        h.on_tool_start({"name": "list_pods"}, "")
        h.on_tool_end({"ok": True, "items": [1, 2, 3]}, name="list_pods")
        assert h.tools_called == 1
        assert h.tool_errors == 0

    def test_on_tool_end_logs_correct_fields(self, caplog):
        h = SREAgentCallbackHandler()
        h.on_tool_start({"name": "list_pods"}, "")
        with caplog.at_level(logging.INFO, logger="app.observability"):
            h.on_tool_end({"ok": True, "items": ["a", "b"]}, name="list_pods")
        assert "event=tool_end" in caplog.text
        assert "tool=list_pods" in caplog.text
        assert "ok=True" in caplog.text
        assert "items=2" in caplog.text
        assert "latency_ms=" in caplog.text

    def test_on_tool_error_increments_counter(self, caplog):
        h = SREAgentCallbackHandler()
        h.on_tool_start({"name": "get_pod"}, "")
        with caplog.at_level(logging.ERROR, logger="app.observability"):
            h.on_tool_error(RuntimeError("boom"), name="get_pod")
        assert h.tool_errors == 1
        assert h.tools_called == 0
        assert "event=tool_error" in caplog.text
        assert "tool=get_pod" in caplog.text
        assert "latency_ms=" in caplog.text

    def test_on_llm_end_accumulates_tokens(self):
        h = SREAgentCallbackHandler()
        h.on_llm_end(_make_llm_result(100, 50))
        h.on_llm_end(_make_llm_result(200, 75))
        assert h.input_tokens == 300
        assert h.output_tokens == 125

    def test_on_llm_end_logs_token_counts(self, caplog):
        h = SREAgentCallbackHandler()
        with caplog.at_level(logging.INFO, logger="app.observability"):
            h.on_llm_end(_make_llm_result(1000, 500))
        assert "event=llm_tokens" in caplog.text
        assert "input=1000" in caplog.text
        assert "output=500" in caplog.text
        assert "cost" not in caplog.text

    def test_on_llm_end_missing_usage_metadata_no_crash(self):
        h = SREAgentCallbackHandler()
        msg = SimpleNamespace(usage_metadata=None)
        gen = SimpleNamespace(message=msg)
        result = SimpleNamespace(generations=[[gen]])
        h.on_llm_end(result)
        assert h.input_tokens == 0
        assert h.output_tokens == 0

    def test_on_llm_end_no_generations_no_crash(self):
        h = SREAgentCallbackHandler()
        h.on_llm_end(SimpleNamespace(generations=[]))
        assert h.input_tokens == 0

    def test_emit_request_summary_fields(self, caplog):
        h = SREAgentCallbackHandler()
        h.on_tool_start({"name": "list_pods"}, "")
        h.on_tool_end({"ok": True, "items": []}, name="list_pods")
        h.on_llm_end(_make_llm_result(100, 50))
        with caplog.at_level(logging.INFO, logger="app.observability"):
            h.emit_request_summary("Are pods healthy?")
        assert "event=request_summary" in caplog.text
        assert "tools_called=1" in caplog.text
        assert "tool_errors=0" in caplog.text
        assert "input_tokens=100" in caplog.text
        assert "output_tokens=50" in caplog.text
        assert "wall_ms=" in caplog.text
        assert "timeout=False" in caplog.text
        assert "cost" not in caplog.text

    def test_emit_request_summary_timeout_flag(self, caplog):
        h = SREAgentCallbackHandler()
        with caplog.at_level(logging.INFO, logger="app.observability"):
            h.emit_request_summary("test", timed_out=True)
        assert "timeout=True" in caplog.text


class TestMakeCallbacks:
    def test_returns_only_handler_when_no_langfuse_key(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        callbacks, handler = make_callbacks()
        assert len(callbacks) == 1
        assert isinstance(handler, SREAgentCallbackHandler)

    def test_returns_two_callbacks_when_langfuse_configured(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        mock_lf = MagicMock()
        with patch.dict("sys.modules", {"langfuse.langchain": mock_lf}):
            mock_lf.CallbackHandler = MagicMock(return_value=MagicMock())
            callbacks, handler = make_callbacks()
        assert len(callbacks) == 2
        assert isinstance(handler, SREAgentCallbackHandler)
