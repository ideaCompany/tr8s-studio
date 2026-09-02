"""
Tests for the chat tool-calling loop, with a scripted fake client.

There were no API credentials on the machine this was written on, so the
request/response path itself is still unverified against the real API. What
these do cover is everything around it: that tool calls are executed and their
results fed back correctly, that all results go back in ONE user message (the
API silently degrades parallel tool use otherwise), that thinking blocks are
echoed rather than dropped, and that failures are reported instead of hidden.
"""

import json
import types

import pytest

from fake import load_fixture_kit, load_fixture_pattern, make_device
from tr8s import chat as chatmod
from tr8s import tools


class Block:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class Response:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kw):
        # snapshot the message list: the caller passes it by reference and keeps
        # appending, so storing the reference would show later turns too
        kw = dict(kw)
        kw["messages"] = list(kw.get("messages", []))
        self.calls.append(kw)
        if not self.script:
            return Response([Block("text", text="done")], "end_turn")
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


@pytest.fixture
def wired_chat(monkeypatch):
    d, t = make_device(patterns={0: load_fixture_pattern()},
                       kits={0: load_fixture_kit()})
    tools.set_device(d)
    monkeypatch.setattr(chatmod, "available", lambda: (True, "ready"))
    yield d, t
    tools.set_device(None)


def make_chat(script, monkeypatch):
    c = chatmod.Chat.__new__(chatmod.Chat)      # bypass the credential check
    c.client = FakeClient(script)
    c.model = "test-model"
    c.messages = []
    return c


# ------------------------------------------------------------------ tool specs

def test_tool_specs_match_the_registry():
    specs = chatmod.tool_specs()
    assert len(specs) == len(tools.REGISTRY)
    for s in specs:
        assert set(s) == {"name", "description", "input_schema"}
        assert "." not in s["name"], "dotted names are rejected by the API"


def test_name_mapping_round_trips():
    for real in tools.REGISTRY:
        flat = chatmod._mcp_name(real)
        assert chatmod._registry_name(flat) == real


# ------------------------------------------------------------------- the loop

def test_plain_answer_needs_no_tools(wired_chat, monkeypatch):
    c = make_chat([Response([Block("text", text="hello there")], "end_turn")],
                  monkeypatch)
    events = []
    reply = c.send("hi", emit=events.append)
    assert reply == "hello there"
    assert [e["type"] for e in events] == ["thinking", "text", "done"]


def test_a_tool_call_is_executed_and_fed_back(wired_chat, monkeypatch):
    script = [
        Response([Block("tool_use", id="t1", name="pattern_get",
                        input={"slot": 0})], "tool_use"),
        Response([Block("text", text="that pattern is called Sakura")], "end_turn"),
    ]
    c = make_chat(script, monkeypatch)
    events = []
    reply = c.send("what is in slot 0?", emit=events.append)

    assert "Sakura" in reply
    kinds = [e["type"] for e in events]
    assert "tool" in kinds and "result" in kinds
    result_ev = next(e for e in events if e["type"] == "result")
    assert result_ev["ok"] is True

    # the tool result must be returned to the model, in a user message
    second = c.client.messages.calls[1]["messages"]
    last = second[-1]
    assert last["role"] == "user"
    blocks = last["content"]
    assert all(b["type"] == "tool_result" for b in blocks)
    assert blocks[0]["tool_use_id"] == "t1"
    assert "Sakura" in blocks[0]["content"]


def test_parallel_tool_calls_return_in_one_message(wired_chat, monkeypatch):
    """Splitting results across messages trains the model out of parallel calls."""
    script = [
        Response([
            Block("tool_use", id="a", name="pattern_get", input={"slot": 0}),
            Block("tool_use", id="b", name="device_info", input={}),
        ], "tool_use"),
        Response([Block("text", text="both read")], "end_turn"),
    ]
    c = make_chat(script, monkeypatch)
    c.send("read two things", emit=lambda e: None)

    user_msgs = [m for m in c.client.messages.calls[1]["messages"]
                 if m["role"] == "user" and isinstance(m["content"], list)]
    assert len(user_msgs) == 1, "results were split across messages"
    assert [b["tool_use_id"] for b in user_msgs[0]["content"]] == ["a", "b"]


def test_thinking_blocks_are_echoed_back(wired_chat, monkeypatch):
    """The API requires thinking blocks to be replayed unchanged."""
    thinking = Block("thinking", thinking="considering")
    script = [
        Response([thinking, Block("tool_use", id="t1", name="device_info",
                                  input={})], "tool_use"),
        Response([Block("text", text="ok")], "end_turn"),
    ]
    c = make_chat(script, monkeypatch)
    c.send("go", emit=lambda e: None)
    assistant = [m for m in c.client.messages.calls[1]["messages"]
                 if m["role"] == "assistant"][0]
    assert thinking in assistant["content"], "thinking block was dropped"


def test_a_failing_tool_is_reported_not_swallowed(wired_chat, monkeypatch):
    script = [
        Response([Block("tool_use", id="t1", name="pattern_get",
                        input={"slot": 999})], "tool_use"),
        Response([Block("text", text="that slot does not exist")], "end_turn"),
    ]
    c = make_chat(script, monkeypatch)
    events = []
    c.send("read slot 999", emit=events.append)
    result_ev = next(e for e in events if e["type"] == "result")
    assert result_ev["ok"] is False
    blocks = c.client.messages.calls[1]["messages"][-1]["content"]
    assert blocks[0]["is_error"] is True
    assert "999" in blocks[0]["content"]


def test_unknown_tool_name_is_an_error_result(wired_chat, monkeypatch):
    script = [
        Response([Block("tool_use", id="t1", name="not_a_tool", input={})],
                 "tool_use"),
        Response([Block("text", text="sorry")], "end_turn"),
    ]
    c = make_chat(script, monkeypatch)
    events = []
    c.send("do something impossible", emit=events.append)
    ev = next(e for e in events if e["type"] == "result")
    assert ev["ok"] is False and "unknown tool" in ev["summary"]


def test_api_failure_surfaces_rather_than_raising(wired_chat, monkeypatch):
    class Boom:
        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("connection reset")
    c = chatmod.Chat.__new__(chatmod.Chat)
    c.client = Boom()
    c.model = "test"
    c.messages = []
    events = []
    reply = c.send("hello", emit=events.append)
    assert "connection reset" in reply
    assert any(e["type"] == "error" for e in events)


def test_history_persists_across_turns(wired_chat, monkeypatch):
    c = make_chat([Response([Block("text", text="one")], "end_turn"),
                   Response([Block("text", text="two")], "end_turn")],
                  monkeypatch)
    c.send("first", emit=lambda e: None)
    c.send("second", emit=lambda e: None)
    roles = [m["role"] for m in c.client.messages.calls[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    c.reset()
    assert c.messages == []


def test_runaway_loop_is_bounded(wired_chat, monkeypatch):
    """A model that only ever calls tools must not spin forever."""
    endless = [Response([Block("tool_use", id=f"t{i}", name="device_info",
                               input={})], "tool_use")
               for i in range(chatmod.MAX_TURNS + 5)]
    c = make_chat(endless, monkeypatch)
    events = []
    c.send("loop forever", emit=events.append)
    assert len(c.client.messages.calls) <= chatmod.MAX_TURNS
    assert any(e["type"] == "error" and "stopped after" in e["message"]
               for e in events)


def test_system_prompt_states_the_hard_constraints():
    """An agent must not promise what the hardware cannot do."""
    s = chatmod.SYSTEM
    for phrase in ("MOTION", "LEVEL", "SAMPLE", "PTN"):
        assert phrase in s, f"the system prompt should mention {phrase}"
    assert "undo" in s.lower()


def test_system_prompt_points_at_the_generators():
    """Hand-written step strings do not survive 'same but sparser'."""
    s = chatmod.SYSTEM
    for name in ("track_create", "styles_list", "kit_auto_build",
                 "pattern_arrange", "pattern_set_line", "history_undo",
                 "library_list", "library_load", "kit_fix", "kit_tune_to",
                 "track_remix"):
        assert name in s, f"the prompt never mentions {name}"


def test_system_prompt_warns_about_the_kit_reference_trap():
    """The machine re-points the last pattern written at the next kit committed."""
    s = chatmod.SYSTEM.lower()
    assert "commit every kit before writing any" in s


def test_system_prompt_translates_the_words_musicians_use():
    s = chatmod.SYSTEM.lower()
    for word in ("hypnotic", "peak time", "dubby", "acid", "phrygian"):
        assert word in s, f"the prompt cannot interpret {word!r}"


def test_every_tool_named_in_the_prompt_exists():
    """A prompt that names a tool the registry lacks sends the model nowhere."""
    import re
    flat = {chatmod._mcp_name(n) for n in tools.REGISTRY}
    # parameter names look exactly like tool names in backticks (`kit_slot`),
    # so they have to be excluded by knowing what the parameters actually are
    params = {k for spec in tools.REGISTRY.values()
              for k in spec["input_schema"]["properties"]}
    namespaces = {n.split(".")[0] for n in tools.REGISTRY}
    for name in re.findall(r"`([a-z]+_[a-z_]+)`", chatmod.SYSTEM):
        if name in params or name.split("_")[0] not in namespaces:
            continue
        assert name in flat, f"the prompt names {name}, which does not exist"
