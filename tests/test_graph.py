from unittest.mock import MagicMock, patch


@patch("app.graph.create_react_agent")
@patch("app.graph.ChatAnthropic")
def test_build_agent_returns_runnable(mock_anthropic_cls, mock_create_react):
    mock_anthropic_cls.return_value = MagicMock()
    mock_create_react.return_value = MagicMock()
    from app.graph import build_agent

    agent = build_agent()

    assert hasattr(agent, "invoke")
    mock_anthropic_cls.assert_called_once_with(model="claude-haiku-4-5-20251001")
    mock_create_react.assert_called_once()


@patch("app.graph.ChatAnthropic")
def test_build_agent_registers_all_tools(mock_anthropic_cls):
    mock_anthropic_cls.return_value = MagicMock()
    from app.graph import TOOLS

    assert len(TOOLS) == 7
    tool_names = {t.name for t in TOOLS}
    assert tool_names == {
        "list_pods",
        "list_nodes",
        "list_events",
        "list_deployments",
        "get_pod",
        "get_deployment",
        "get_pod_logs",
    }


@patch("app.graph.create_react_agent")
@patch("app.graph.ChatAnthropic")
def test_build_agent_passes_checkpointer(mock_anthropic_cls, mock_create_react):
    mock_anthropic_cls.return_value = MagicMock()
    mock_cp = MagicMock()
    from app.graph import build_agent

    build_agent(checkpointer=mock_cp)

    _, kwargs = mock_create_react.call_args
    assert kwargs["checkpointer"] is mock_cp
