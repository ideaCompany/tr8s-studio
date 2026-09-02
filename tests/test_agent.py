"""
The Claude Code chat backend, minus Claude: the tool bridge, the key handling
and the credential choice are pure and testable; the SDK itself is not
exercised here (it needs a sign-in and a network).
"""

import json
import os

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import agent, config, tools


@pytest.fixture
def wired():
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def test_a_tool_result_is_text_the_model_can_read(wired):
    out = agent.run_tool("pattern.get", {"slot": "1-01"})
    assert "is_error" not in out
    body = json.loads(out["content"][0]["text"])
    assert body["name"] == "Sakura"


def test_a_failing_tool_is_an_error_result_not_an_exception(wired):
    out = agent.run_tool("pattern.get", {"slot": "9-99"})
    assert out["is_error"] is True
    assert out["content"][0]["type"] == "text"


def test_an_unknown_tool_is_an_error_result(wired):
    out = agent.run_tool("pattern.nope", {})
    assert out["is_error"] is True


def test_a_mutating_tool_is_logged_as_the_ai(wired):
    from tr8s.changelog import CHANGELOG
    CHANGELOG.clear()
    out = agent.run_tool("pattern.set_steps",
                         {"slot": "1-01", "variation": "A", "instrument": "BD",
                          "steps": "X...X...X...X..."})
    assert "is_error" not in out, out
    entries = CHANGELOG.recent(5, "ai")
    assert entries and entries[-1]["instrument"] == "BD"


def test_the_mcp_server_offers_every_registry_tool():
    pytest.importorskip("claude_agent_sdk")
    server = agent.build_server()
    assert server["type"] == "sdk" and server["name"] == "tr8s"


def test_a_pasted_key_is_validated_and_kept_private(tmp_path):
    with pytest.raises(ValueError):
        agent.save_key("hello")
    agent.save_key("sk-ant-api03-" + "x" * 40)
    assert agent.saved_key().startswith("sk-ant-")
    mode = oct(os.stat(config.settings_path()).st_mode & 0o777)
    assert mode == "0o600", mode
    agent.save_key(None)
    assert agent.saved_key() is None


def test_auth_mode_defaults_to_the_key_when_there_is_no_sign_in(monkeypatch):
    monkeypatch.setattr(agent, "auth_status", lambda max_age=15.0: {"loggedIn": False})
    monkeypatch.setattr(agent, "api_key", lambda: "sk-ant-x")
    assert agent.auth_mode() == "apikey"
    monkeypatch.setattr(agent, "api_key", lambda: None)
    assert agent.auth_mode() == "claude"
    agent.set_auth_mode("apikey")
    assert agent.auth_mode() == "apikey"
    with pytest.raises(ValueError):
        agent.set_auth_mode("openai")


def test_testing_an_empty_key_says_so():
    assert agent.test_key("") == {"ok": False, "error": "no key"}


def test_a_device_select_by_the_assistant_is_reported(wired, monkeypatch):
    """The machine sends no Program Change for a SysEx select, so the studio
    must be told by the tool bridge itself."""
    moved = []
    monkeypatch.setattr(agent, "on_machine_moved", moved.append)
    d, t = wired
    d.playing = lambda: False
    out = agent.run_tool("device.select", {"pattern": "1-01"})
    assert "is_error" not in out, out
    assert moved == [0]


def test_the_studio_context_names_the_pattern_and_the_transport(wired):
    from tr8s.server import Studio
    s = Studio()
    s.select(0)
    ctx = s.chat_context()
    assert '1-01 "Sakura"' in ctx
    assert "machine: stopped" in ctx
    assert "variations with steps:" in ctx


def test_the_studio_follows_an_assistant_move(wired):
    from tr8s.server import Studio
    s = Studio()
    s.slot = 5
    s._machine_moved_by_tool(0)
    assert s.slot == 0 and s.pattern["name"] == "Sakura"
