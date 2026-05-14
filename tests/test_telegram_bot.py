import pytest
from app.telegram_bot import extract_answer, parse_allowed_chat_ids, TELEGRAM_MAX_LENGTH


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
