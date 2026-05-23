import logging
import os
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


class SREAgentCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        super().__init__()
        self._start_time = time.monotonic()
        self._tool_starts: dict[str, float] = {}
        self.tools_called: int = 0
        self.tool_errors: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        name = serialized.get("name", "unknown")
        self._tool_starts[name] = time.monotonic()
        logger.info("event=tool_start tool=%s", name)

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        name = kwargs.get("name", "unknown")
        latency_ms = int((time.monotonic() - self._tool_starts.pop(name, time.monotonic())) * 1000)
        self.tools_called += 1

        ok = True
        items = None
        if isinstance(output, dict):
            ok = bool(output.get("ok", True))
            items = len(output.get("items", [])) if "items" in output else None
        elif hasattr(output, "ok"):
            ok = bool(output.ok)

        if items is not None:
            logger.info("event=tool_end tool=%s ok=%s items=%d latency_ms=%d", name, ok, items, latency_ms)
        else:
            logger.info("event=tool_end tool=%s ok=%s latency_ms=%d", name, ok, latency_ms)

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        name = kwargs.get("name", "unknown")
        latency_ms = int((time.monotonic() - self._tool_starts.pop(name, time.monotonic())) * 1000)
        self.tool_errors += 1
        logger.error("event=tool_error tool=%s error=%s latency_ms=%d", name, error, latency_ms)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            usage = response.generations[0][0].message.usage_metadata  # type: ignore[index]
            if usage:
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
        except (IndexError, AttributeError):
            pass
        logger.info("event=llm_tokens input=%d output=%d", self.input_tokens, self.output_tokens)

    def emit_request_summary(self, question: str, timed_out: bool = False) -> None:
        wall_ms = int((time.monotonic() - self._start_time) * 1000)
        logger.info(
            "event=request_summary tools_called=%d tool_errors=%d "
            "input_tokens=%d output_tokens=%d wall_ms=%d timeout=%s",
            self.tools_called,
            self.tool_errors,
            self.input_tokens,
            self.output_tokens,
            wall_ms,
            timed_out,
        )


def make_callbacks() -> tuple[list, "SREAgentCallbackHandler"]:
    handler = SREAgentCallbackHandler()
    callbacks: list = [handler]
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        from langfuse.callback import CallbackHandler as LFHandler  # type: ignore[import]
        callbacks.append(LFHandler())
    return callbacks, handler
