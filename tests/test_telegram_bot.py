import pytest
from app.telegram_bot import parse_allowed_chat_ids


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
