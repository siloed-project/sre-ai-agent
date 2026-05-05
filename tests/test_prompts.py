from app.prompts import SYSTEM_PROMPT


def test_system_prompt_is_non_empty_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 50


def test_system_prompt_requires_evidence():
    assert "tool result" in SYSTEM_PROMPT.lower() or "evidence" in SYSTEM_PROMPT.lower()


def test_system_prompt_enforces_read_only():
    assert "read-only" in SYSTEM_PROMPT.lower() or "mutation" in SYSTEM_PROMPT.lower()


def test_system_prompt_handles_insufficient_data():
    assert "insufficient" in SYSTEM_PROMPT.lower()
