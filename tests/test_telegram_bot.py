import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

import app.telegram_bot as telegram_bot
from app.approvals import ApprovalStore
from app.telegram_bot import (
    TELEGRAM_MAX_LENGTH,
    extract_answer,
    handle_approval,
    handle_message,
    invoke_with_history_recovery,
    parse_allowed_chat_ids,
)


@pytest.fixture(autouse=True)
def disable_external_callbacks(monkeypatch):
    handler = MagicMock()
    monkeypatch.setattr(telegram_bot, "make_callbacks", lambda: ([], handler))

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(telegram_bot.asyncio, "to_thread", run_inline)


def test_parse_single_id():
    assert parse_allowed_chat_ids("12345") == frozenset({12345})


def test_parse_multiple_ids():
    assert parse_allowed_chat_ids("12345,67890") == frozenset({12345, 67890})


def test_parse_ids_with_spaces():
    assert parse_allowed_chat_ids("12345, 67890") == frozenset({12345, 67890})


def test_parse_empty_string_raises():
    with pytest.raises(ValueError):
        parse_allowed_chat_ids("")


def test_parse_non_numeric_raises():
    with pytest.raises(ValueError):
        parse_allowed_chat_ids("abc")


def test_extract_answer_section_strips_investigation():
    content = (
        "Investigation:\n- Step 1: checked pods\n\n"
        "Answer:\nAll pods are healthy.\n\n"
        "Evidence:\n- default/api-pod: Running"
    )
    result = extract_answer(content)
    assert result.startswith("Answer:")
    assert "Investigation" not in result
    assert "All pods are healthy" in result


def test_extract_answer_no_section_returns_full():
    content = "Some raw response without an Answer section"
    result = extract_answer(content)
    assert result == content


def test_extract_answer_truncates_long_content():
    content = "Answer:\n" + "x" * 5000
    result = extract_answer(content)
    assert len(result) <= TELEGRAM_MAX_LENGTH
    assert result.endswith("...")


def test_extract_answer_short_content_unchanged():
    content = "Answer:\nShort response."
    result = extract_answer(content)
    assert result == content


def test_extract_answer_exactly_at_limit_unchanged():
    content = "Answer:\n" + "x" * (TELEGRAM_MAX_LENGTH - len("Answer:\n"))
    result = extract_answer(content)
    assert len(result) == TELEGRAM_MAX_LENGTH
    assert not result.endswith("...")


def _make_update(chat_id: int, text: str):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = chat_id
    update.message.text = text
    reply_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=reply_msg)
    return update, reply_msg


def _make_agent(answer: str):
    agent = MagicMock()
    agent.invoke.return_value = {
        "messages": [AIMessage(content=f"Answer:\n{answer}\n\nEvidence:\n- ns/pod: Running")]
    }
    return agent


def test_invalid_history_resets_thread_and_retries_current_message():
    agent = MagicMock()
    expected = {"messages": [AIMessage(content="Answer:\nRecovered.")]}
    agent.invoke.side_effect = [
        ValueError(
            "Found AIMessages with tool_calls that do not have a corresponding "
            "ToolMessage. For troubleshooting, visit: "
            "https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CHAT_HISTORY"
        ),
        expected,
    ]
    message = HumanMessage(content="Are any pods unhealthy?")
    config = {"configurable": {"thread_id": "12345"}}

    result = invoke_with_history_recovery(agent, message, config, "12345")

    assert result == expected
    agent.checkpointer.delete_thread.assert_called_once_with("12345")
    assert agent.invoke.call_count == 2


def test_non_history_value_error_is_not_retried():
    agent = MagicMock()
    agent.invoke.side_effect = ValueError("unrelated failure")

    with pytest.raises(ValueError, match="unrelated failure"):
        invoke_with_history_recovery(
            agent,
            HumanMessage(content="hello"),
            {"configurable": {"thread_id": "12345"}},
            "12345",
        )

    agent.checkpointer.delete_thread.assert_not_called()
    agent.invoke.assert_called_once()


async def test_allowed_chat_id_receives_answer():
    update, reply_msg = _make_update(12345, "Are any pods unhealthy?")
    agent = _make_agent("All pods are healthy.")
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    reply_msg.edit_text.assert_called_once()
    assert "healthy" in reply_msg.edit_text.call_args[0][0]
    invoke_config = agent.invoke.call_args.kwargs["config"]
    assert invoke_config["configurable"]["thread_id"] == "12345"
    assert invoke_config["metadata"]["thread_id"] == "12345"
    assert invoke_config["metadata"]["langfuse_session_id"] == "telegram:12345"


async def test_disallowed_chat_id_is_silently_dropped():
    update, reply_msg = _make_update(99999, "Are any pods unhealthy?")
    agent = _make_agent("All pods are healthy.")
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    update.message.reply_text.assert_not_called()


async def test_agent_exception_replies_with_error():
    update, reply_msg = _make_update(12345, "Are any pods unhealthy?")
    agent = MagicMock()
    agent.invoke.side_effect = RuntimeError("K8s API unreachable")
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    reply_msg.edit_text.assert_called_once()
    assert "Error" in reply_msg.edit_text.call_args[0][0]


async def test_timeout_replies_with_timeout_message():
    update, reply_msg = _make_update(12345, "Are any pods unhealthy?")
    agent = MagicMock()
    with patch("app.telegram_bot.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await handle_message(update, MagicMock(), agent, frozenset({12345}))
    active_task = telegram_bot._active_invocations.pop("12345", None)
    if active_task is not None and not active_task.done():
        active_task.cancel()
    reply_msg.edit_text.assert_called_once()
    assert "timed out" in reply_msg.edit_text.call_args[0][0].lower()


async def test_active_invocation_blocks_same_chat():
    update, reply_msg = _make_update(12345, "Are any pods unhealthy?")
    agent = _make_agent("This should not run.")
    active_task = asyncio.create_task(asyncio.sleep(60))
    telegram_bot._active_invocations["12345"] = active_task

    try:
        await handle_message(update, MagicMock(), agent, frozenset({12345}))
    finally:
        active_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active_task
        telegram_bot._active_invocations.pop("12345", None)

    update.message.reply_text.assert_called_once()
    assert "still finishing" in update.message.reply_text.call_args[0][0]
    agent.invoke.assert_not_called()
    reply_msg.edit_text.assert_not_called()


async def test_list_content_is_handled_gracefully():
    update, reply_msg = _make_update(12345, "List pods")
    agent = MagicMock()
    agent.invoke.return_value = {
        "messages": [AIMessage(content=[{"type": "text", "text": "Answer:\nNo issues found."}])]
    }
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    reply_msg.edit_text.assert_called_once()
    assert "No issues found" in reply_msg.edit_text.call_args[0][0]


async def test_mutation_interrupt_renders_native_approval_buttons(tmp_path):
    update, reply_msg = _make_update(12345, "Restart the api deployment")
    agent = MagicMock()
    agent.invoke.return_value = {
        "messages": [AIMessage(content="")],
        "__interrupt__": (
            SimpleNamespace(
                id="interrupt-1",
                value={
                    "kind": "mutation_approval",
                    "action": "restart_deployment",
                    "summary": "Restart deployment default/api",
                    "parameters": {"namespace": "default", "name": "api"},
                },
            ),
        ),
    }
    store = ApprovalStore(str(tmp_path / "approvals.db"))

    await handle_message(update, MagicMock(), agent, frozenset({12345}), store)

    text = reply_msg.edit_text.call_args.args[0]
    markup = reply_msg.edit_text.call_args.kwargs["reply_markup"]
    assert "Approval required" in text
    assert "default/api" in text
    assert markup.inline_keyboard[0][0].text == "✅ Approve"
    assert markup.inline_keyboard[0][1].text == "❌ Reject"


async def test_pending_mutation_blocks_another_message(tmp_path):
    update, reply_msg = _make_update(12345, "Start another investigation")
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    store.create(
        thread_id="12345",
        chat_id=12345,
        user_id=12345,
        payload={"kind": "mutation_approval", "action": "delete_pod"},
    )
    agent = _make_agent("This should not run.")

    await handle_message(update, MagicMock(), agent, frozenset({12345}), store)

    update.message.reply_text.assert_called_once()
    assert "awaiting approval" in update.message.reply_text.call_args.args[0]
    agent.invoke.assert_not_called()
    reply_msg.edit_text.assert_not_called()


async def test_approval_resumes_saved_graph_once(tmp_path):
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    approval = store.create(
        thread_id="12345",
        chat_id=12345,
        user_id=12345,
        payload={
            "kind": "mutation_approval",
            "action": "delete_pod",
            "summary": "Delete pod default/api-123",
            "parameters": {"namespace": "default", "name": "api-123"},
        },
    )
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user.id = 12345
    update.callback_query.data = f"mutation:approve:{approval.approval_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    agent = _make_agent("Mutation failed: forbidden by RBAC.")

    await handle_approval(
        update,
        MagicMock(),
        agent,
        frozenset({12345}),
        store,
    )

    first_input = agent.invoke.call_args.args[0]
    assert isinstance(first_input, Command)
    assert first_input.resume is True
    assert update.callback_query.edit_message_text.call_count == 2
    assert "forbidden" in update.callback_query.edit_message_text.call_args.args[0]

    with pytest.raises(ValueError, match="already been handled"):
        store.claim(
            approval.approval_id,
            chat_id=12345,
            user_id=12345,
            decision="approved",
        )
