from unittest.mock import MagicMock, patch

import pytest

from app.main import main


def test_main_exits_with_usage_when_no_args(capsys):
    with patch("sys.argv", ["app.main"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Usage" in captured.out


@patch("app.main.build_agent")
def test_main_invokes_agent_with_question(mock_build, capsys):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [MagicMock(content="2 pods are unhealthy.")]
    }
    mock_build.return_value = mock_agent

    with patch("sys.argv", ["app.main", "Which pods are unhealthy?"]):
        main()

    call_args = mock_agent.invoke.call_args[0][0]
    assert call_args["messages"][0].content == "Which pods are unhealthy?"
    captured = capsys.readouterr()
    assert "2 pods are unhealthy." in captured.out


@patch("app.main.build_agent")
def test_main_exits_on_agent_init_error(mock_build, capsys):
    mock_build.side_effect = Exception("no kubeconfig found")

    with patch("sys.argv", ["app.main", "What is broken?"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "no kubeconfig found" in captured.out
