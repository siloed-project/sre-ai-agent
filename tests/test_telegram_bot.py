import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.telegram_bot import extract_answer, handle_message, parse_allowed_chat_ids, TELEGRAM_MAX_LENGTH


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


async def test_allowed_chat_id_receives_answer():
    update, reply_msg = _make_update(12345, "Are any pods unhealthy?")
    agent = _make_agent("All pods are healthy.")
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    reply_msg.edit_text.assert_called_once()
    assert "healthy" in reply_msg.edit_text.call_args[0][0]
    invoke_config = agent.invoke.call_args.kwargs["config"]
    assert invoke_config["configurable"]["thread_id"] == "12345"


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
    reply_msg.edit_text.assert_called_once()
    assert "timed out" in reply_msg.edit_text.call_args[0][0].lower()


async def test_list_content_is_handled_gracefully():
    update, reply_msg = _make_update(12345, "List pods")
    agent = MagicMock()
    agent.invoke.return_value = {
        "messages": [AIMessage(content=[{"type": "text", "text": "Answer:\nNo issues found."}])]
    }
    await handle_message(update, MagicMock(), agent, frozenset({12345}))
    reply_msg.edit_text.assert_called_once()
    assert "No issues found" in reply_msg.edit_text.call_args[0][0]
