"""
Tests for the device facade and the tool registry, using a fake transport that
replays captured blobs. No hardware required.
"""

import json

import pytest

from fake import (FakeTransport, load_empty_kit, load_fixture_kit,
                  load_fixture_pattern, make_device)
from tr8s import tools
from tr8s.tools import ToolError
from tr8s.device import Device, DeviceError, panel_to_slot, slot_to_panel
from tr8s.kit import Kit
from tr8s.pattern import Pattern


# ------------------------------------------------------------------ numbering

def test_panel_slot_roundtrip():
    assert panel_to_slot(8, 3) == 114
    assert slot_to_panel(114) == "8-03"
    assert panel_to_slot(1, 1) == 0
    assert slot_to_panel(0) == "1-01"
    for slot in range(128):
        b, i = slot // 16 + 1, slot % 16 + 1
        assert panel_to_slot(b, i) == slot


def test_panel_rejects_out_of_range():
    for bad in ((0, 1), (9, 1), (1, 0), (1, 17)):
        with pytest.raises(ValueError):
            panel_to_slot(*bad)


# --------------------------------------------------------------------- device

def test_read_pattern_from_fixture():
    d, _ = make_device()
    p = d.read_pattern(0)
    assert isinstance(p, Pattern)
    assert p.name == "Sakura"
    assert 40 <= p.tempo <= 300


def test_read_missing_slot_raises():
    d, _ = make_device(patterns={})
    with pytest.raises(DeviceError):
        d.read_pattern(7)


def test_write_pattern_verifies():
    d, t = make_device()
    p = d.read_pattern(0)
    p.name = "WRITTEN"
    p.set_steps("A", "BD", "X...x...X...x...")
    r = d.write_pattern(5, p)
    assert r["committed"] and r["verified"]
    assert ("pattern", 5) in t.commits
    assert d.read_pattern(5).get_steps("A", "BD") == "X...x...X...x..."


def test_uncommitted_write_still_changes_the_slot():
    """The device has no scratch buffer; commit=False is not an undo."""
    d, t = make_device()
    p = d.read_pattern(0)
    p.set_steps("A", "RC", "X" * 16)
    r = d.write_pattern(0, p, commit=False)
    assert r["committed"] is False
    assert ("pattern", 0) not in t.commits
    assert d.read_pattern(0).get_steps("A", "RC") == "X" * 16   # slot changed


def test_kit_write_ignores_level_when_verifying():
    """The fader overwrites level, so verification must not fail on it."""
    d, t = make_device()
    k = d.read_kit(0)
    k.set("BD", "tune", -20)
    r = d.write_kit(3, k)
    assert r["verified"], "level differing must not fail verification"
    assert d.read_kit(3).get("BD", "tune") == -20
    assert d.read_kit(3).get("BD", "level") == t.fader_level


def test_backup_and_restore(tmp_path, monkeypatch):
    from tr8s import config
    monkeypatch.setenv("TR8S_DATA", str(tmp_path))
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    d, t = make_device(patterns={0: load_fixture_pattern(), 1: load_fixture_pattern()},
                       kits={0: load_fixture_kit()})
    counts = d.backup(kinds=("pattern",), lo=0, hi=1)
    assert counts["pattern"] == 2
    # mutate the device, then restore from the backup
    p = d.read_pattern(0)
    p.set_steps("A", "CC", "X" * 16)
    d.write_pattern(0, p)
    assert d.read_pattern(0).get_steps("A", "CC") == "X" * 16
    d.restore("pattern", 0)
    assert d.read_pattern(0).get_steps("A", "CC") != "X" * 16


def test_slot_bounds():
    d, _ = make_device()
    for bad in (-1, 128, 999):
        with pytest.raises(ValueError):
            d.read_pattern(bad)


# ---------------------------------------------------------------------- tools

@pytest.fixture
def wired(monkeypatch):
    d, t = make_device(patterns={0: load_fixture_pattern(),
                                 1: load_fixture_pattern(),
                                 114: load_fixture_pattern()},
                       kits={0: load_fixture_kit(), 61: load_fixture_kit(),
                             89: load_fixture_kit()})
    tools.set_device(d)
    yield d, t
    tools.set_device(None)


def test_every_tool_has_a_usable_schema():
    for t in tools.schemas():
        s = t["input_schema"]
        assert s["type"] == "object"
        assert isinstance(s["properties"], dict)
        assert isinstance(s["required"], list)
        assert set(s["required"]) <= set(s["properties"])
        # the optional marker must never leak into a published schema
        for prop in s["properties"].values():
            assert "_optional" not in prop
        assert isinstance(t["mutates_device"], bool)
        assert t["description"].strip()


def test_tool_names_are_api_safe():
    import re
    for t in tools.schemas():
        flat = t["name"].replace(".", "_")
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", flat), t["name"]


def test_unknown_tool_and_bad_args(wired):
    with pytest.raises(tools.ToolError):
        tools.call("nope.nope", {})
    with pytest.raises(tools.ToolError) as e:
        tools.call("pattern.get", {"slot": 0, "bogus": 1})
    assert "unexpected" in str(e.value)


def test_slot_parsing_accepts_panel_strings(wired):
    assert tools._slot("8-03") == 114
    assert tools._slot(114) == 114
    assert tools._slot("114") == 114
    with pytest.raises(tools.ToolError):
        tools._slot("nonsense")
    with pytest.raises(tools.ToolError):
        tools._slot(999)


def test_pattern_get_and_set_steps(wired):
    out = tools.call("pattern.get", {"slot": 0})
    assert out["name"] == "Sakura"
    assert out["panel"] == "1-01"
    r = tools.call("pattern.set_steps", {
        "slot": 0, "variation": "B", "instrument": "OH",
        "steps": "..x...x...x...x.", "commit": False})
    assert r["steps"] == "..x...x...x...x."
    assert tools.call("pattern.get", {"slot": 0})["variations"]["B"]["OH"] \
        == "..x...x...x...x."


def test_set_many_is_one_write(wired):
    d, t = wired
    before = len(t.sent)
    tools.call("pattern.set_many", {
        "slot": 0, "variation": "C",
        "tracks": {"BD": "X...x...X...x...", "CH": "x.x.x.x.x.x.x.x."}})
    assert len(t.sent) - before == 1, "set_many must not write once per track"
    v = tools.call("pattern.get", {"slot": 0})["variations"]["C"]
    assert v["BD"] == "X...x...X...x..." and v["CH"] == "x.x.x.x.x.x.x.x."


def test_set_header_only_touches_given_fields(wired):
    before = tools.call("pattern.get", {"slot": 0})
    tools.call("pattern.set_header", {"slot": 0, "tempo": 128.0})
    after = tools.call("pattern.get", {"slot": 0})
    assert after["tempo"] == 128.0
    assert after["name"] == before["name"]
    assert after["kit"] == before["kit"]


def test_header_validation_surfaces_as_tool_error(wired):
    with pytest.raises(tools.ToolError):
        tools.call("pattern.set_header", {"slot": 0, "tempo": 999})
    with pytest.raises(tools.ToolError):
        tools.call("pattern.set_header", {"slot": 0, "scale": "3"})


def test_level_is_not_exposed_as_a_writable_field(wired):
    """The faders own level, so the tool surface must not offer it at all."""
    spec = next(t for t in tools.schemas() if t["name"] == "kit.set_instrument")
    assert "level" not in spec["input_schema"]["properties"]
    with pytest.raises(tools.ToolError) as e:
        tools.call("kit.set_instrument", {"slot": 0, "instrument": "BD",
                                          "level": 200})
    assert "unexpected" in str(e.value)


def test_kit_field_ranges_surface_as_tool_errors(wired):
    with pytest.raises(tools.ToolError) as e:
        tools.call("kit.set_instrument", {"slot": 0, "instrument": "BD",
                                          "lfo": 300})
    assert "0..255" in str(e.value)


def test_kit_set_instrument_applies(wired):
    tools.call("kit.set_instrument", {"slot": 0, "instrument": "SD",
                                      "tune": -30, "decay": 90, "pan": 40})
    inst = tools.call("kit.get", {"slot": 0})["instruments"]["SD"]
    assert (inst["tune"], inst["decay"], inst["pan"]) == (-30, 90, 40)


def test_melody_roundtrip_through_tools(wired):
    tune = "C2 . G2 C3 . D#3 G3 ."
    r = tools.call("pattern.set_melody", {
        "slot": 0, "variation": "D", "instrument": "LT",
        "notes": tune, "root": "C3", "commit": False})
    assert r["warnings"] == []
    back = tools.call("pattern.get_melody", {
        "slot": 0, "variation": "D", "instrument": "LT", "root": "C3"})
    assert back["melody"].startswith("C2 . G2 C3 . D#3 G3 .")


def test_melody_out_of_range_warns_rather_than_silently_transposing(wired):
    r = tools.call("pattern.set_melody", {
        "slot": 0, "variation": "E", "instrument": "LT",
        "notes": "C7", "root": "C3", "commit": False})
    assert r["warnings"] and "outside" in r["warnings"][0]


def test_results_are_json_serialisable(wired):
    for name, args in (("pattern.get", {"slot": 0}),
                       ("kit.get", {"slot": 0}),
                       ("pattern.list", {"lo": 0, "hi": 0})):
        json.dumps(tools.call(name, args), default=str)


def test_mcp_name_mapping_is_bijective():
    from tr8s import mcp_server
    flat = [mcp_server._mcp_name(n) for n in tools.REGISTRY]
    assert len(set(flat)) == len(flat), "flattened tool names must stay unique"
    for real in tools.REGISTRY:
        assert mcp_server._registry_name(mcp_server._mcp_name(real)) == real


# ------------------------------------------------- sample-tone donor handling

def _with_sample_params(kit_blob: bytes, inst: str) -> bytes:
    """A kit whose `inst` record carries sample parameters, as the device writes."""
    from tr8s.kit import Kit
    k = Kit.from_bytes(kit_blob)
    o = Kit.record_offset(inst)
    # exactly what the device writes when a sample tone is assigned
    k.raw[o + 28:o + 42] = bytes([0x18, 0xc8, 0x32, 0, 0, 1, 0, 1, 0,
                                  0xff, 0, 0, 0x20, 0])
    return k.to_bytes()


def test_find_sample_donor_locates_a_populated_record():
    plain = load_empty_kit()
    donor = _with_sample_params(plain, "LT")
    d, _ = make_device(kits={0: plain, 3: donor})
    assert d.find_sample_donor() == (3, "LT")


def test_find_sample_donor_returns_none_when_there_is_no_donor():
    d, _ = make_device(kits={0: load_empty_kit()})
    assert d.find_sample_donor() is None


def test_assigning_a_sample_tone_inherits_a_donor_record(monkeypatch):
    """This is the bug that once made a whole kit inaudible."""
    from tr8s.tones import Tone
    plain = load_empty_kit()
    donor = _with_sample_params(plain, "LT")
    d, _ = make_device(kits={0: plain, 5: donor})
    monkeypatch.setattr(d, "read_tone",
                        lambda tid: Tone(id=tid, name="Fake Saw",
                                         cat="SYNTH2", type=2))
    tools.set_device(d)
    try:
        assert not d.read_kit(0).has_sample_params("MT")
        r = tools.call("kit.set_instrument",
                       {"slot": 0, "instrument": "MT", "tone": 465})
        assert d.read_kit(0).has_sample_params("MT"), \
            "a sample tone must not land on an ACB record"
        assert d.read_kit(0).get("MT", "tone") == 465
        assert any("inherited" in w for w in r["warnings"]), r["warnings"]
    finally:
        tools.set_device(None)


def test_auto_donor_can_be_turned_off(monkeypatch):
    from tr8s.tones import Tone
    d, _ = make_device(kits={0: load_empty_kit()})
    monkeypatch.setattr(d, "read_tone",
                        lambda tid: Tone(id=tid, name="Fake", cat="BASS", type=2))
    tools.set_device(d)
    try:
        r = tools.call("kit.set_instrument",
                       {"slot": 0, "instrument": "MT", "tone": 480,
                        "auto_donor": False})
        assert not d.read_kit(0).has_sample_params("MT")
        assert any("near-silently" in w for w in r["warnings"])
    finally:
        tools.set_device(None)


def test_acb_tone_needs_no_donor(monkeypatch):
    from tr8s.tones import Tone
    d, _ = make_device(kits={0: load_fixture_kit()})
    monkeypatch.setattr(d, "read_tone",
                        lambda tid: Tone(id=tid, name="909 Bass", cat="BD", type=1))
    tools.set_device(d)
    try:
        r = tools.call("kit.set_instrument",
                       {"slot": 0, "instrument": "BD", "tone": 27})
        assert r["warnings"] == []
        assert d.read_kit(0).get("BD", "tone") == 27
    finally:
        tools.set_device(None)


# ------------------------------------------------------- new pattern/kit tools

def test_copy_variation_copies_steps_and_motion(wired):
    tools.call("pattern.set_many", {
        "slot": 0, "variation": "A",
        "tracks": {"BD": "X...x...X...x...", "CH": "x.x.x.x.x.x.x.x."}})
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "A", "instrument": "LT",
        "notes": "C3 . G3 .", "root": "C3"})
    tools.call("pattern.copy_variation", {"slot": 0, "source": "A", "dest": "G"})

    got = tools.call("pattern.get", {"slot": 0})["variations"]
    assert got["G"]["BD"] == "X...x...X...x..."
    assert got["G"]["CH"] == "x.x.x.x.x.x.x.x."
    # the melody must travel with it, not just the step positions
    src = tools.call("pattern.get_melody", {"slot": 0, "variation": "A",
                                            "instrument": "LT", "root": "C3"})
    dst = tools.call("pattern.get_melody", {"slot": 0, "variation": "G",
                                            "instrument": "LT", "root": "C3"})
    assert src["melody"] == dst["melody"]


def test_copy_variation_replaces_the_destination(wired):
    tools.call("pattern.set_many", {"slot": 0, "variation": "H",
                                    "tracks": {"RC": "X" * 16}})
    tools.call("pattern.set_many", {"slot": 0, "variation": "B",
                                    "tracks": {"BD": "X..............."}})
    tools.call("pattern.copy_variation", {"slot": 0, "source": "B", "dest": "H"})
    got = tools.call("pattern.get", {"slot": 0})["variations"]["H"]
    assert "RC" not in got, "the destination must be cleared first"
    assert got["BD"] == "X..............."


def test_copy_variation_rejects_same_source_and_dest(wired):
    with pytest.raises(tools.ToolError):
        tools.call("pattern.copy_variation", {"slot": 0, "source": "A", "dest": "A"})


def test_kit_balance_reports_unmeasured_without_a_catalogue(wired):
    r = tools.call("kit.balance", {"slot": 0})
    assert "measured" in r and "unmeasured" in r
    # with an empty catalogue everything is unmeasured, and it says so
    if not r["measured"]:
        assert "analyse-tones" in r.get("note", "")


def test_kit_balance_uses_measured_peaks(wired, monkeypatch):
    from tr8s.tones import Catalog, Tone
    d, _ = wired
    k = d.read_kit(0)
    tones = {}
    for i, inst in enumerate(["BD", "SD", "LT"]):
        tid = k.get(inst, "tone")
        tones[tid] = Tone(id=tid, name=f"t{i}", cat="BD", type=1,
                          peak=[0.4, 0.05, 0.2][i], centroid=[80, 3000, 90][i])
    monkeypatch.setattr(d, "_catalog", Catalog(tones))
    r = tools.call("kit.balance", {"slot": 0})
    assert r["loudest"] == "BD" and r["quietest"] == "SD"
    assert r["spread_db"] > 15
    # BD at 80 Hz and LT at 90 Hz occupy the same region
    assert any("BD" in c and "LT" in c for c in r.get("possible_masking", []))


def test_transpose_shifts_a_melody(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "B", "instrument": "LT",
        "notes": "C3 . E3 G3", "root": "C3"})
    r = tools.call("pattern.transpose", {
        "slot": 0, "variation": "B", "instrument": "LT", "semitones": 12})
    assert r["transposed_steps"] == 3 and r["warnings"] == []
    back = tools.call("pattern.get_melody", {
        "slot": 0, "variation": "B", "instrument": "LT", "root": "C3"})
    assert back["melody"].startswith("C4 . E4 G4")


def test_transpose_down_an_octave(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "C", "instrument": "LT",
        "notes": "C3 D3", "root": "C3"})
    tools.call("pattern.transpose", {
        "slot": 0, "variation": "C", "instrument": "LT", "semitones": -12})
    back = tools.call("pattern.get_melody", {
        "slot": 0, "variation": "C", "instrument": "LT", "root": "C3"})
    assert back["melody"].startswith("C2 D2")


def test_transpose_clamps_and_warns_at_the_edge(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "D", "instrument": "LT",
        "notes": "C5", "root": "C3"})          # already +24, the ceiling
    r = tools.call("pattern.transpose", {
        "slot": 0, "variation": "D", "instrument": "LT", "semitones": 12})
    assert r["warnings"] and "outside" in r["warnings"][0]


def test_transpose_refuses_when_there_is_no_motion(wired):
    tools.call("pattern.set_many", {"slot": 0, "variation": "E",
                                    "tracks": {"BD": "X..............."}})
    with pytest.raises(tools.ToolError) as e:
        tools.call("pattern.transpose", {"slot": 0, "variation": "E",
                                         "instrument": "BD", "semitones": 5})
    assert "nothing to transpose" in str(e.value)


# --------------------------------------------------------------- export/import

def test_export_import_roundtrip(wired):
    tools.call("pattern.set_header", {"slot": 0, "name": "ROUNDTRIP",
                                      "tempo": 132.0, "shuffle": 40})
    tools.call("pattern.set_many", {
        "slot": 0, "variation": "A",
        "tracks": {"BD": "X...x...X...x...", "CH": "xoxoxoxoxoxoxoxo"}})
    tools.call("pattern.set_many", {
        "slot": 0, "variation": "B", "tracks": {"SD": "....X.......X..."}})

    doc = tools.call("pattern.export", {"slot": 0})
    assert doc["name"] == "ROUNDTRIP" and doc["tempo"] == 132.0
    assert doc["shuffle"] == 40
    # the fixture is a real factory pattern, so every variation has content;
    # what matters is that the ones just written are present and exact
    assert {"A", "B"} <= set(doc["variations"])

    # it must survive a JSON round trip -- that is the point of the format
    import json as _json
    doc = _json.loads(_json.dumps(doc))

    tools.call("pattern.set_header", {"slot": 1, "name": "SCRATCH"})
    r = tools.call("pattern.import", {"slot": 1, "pattern": doc})
    assert r["warnings"] == []
    got = tools.call("pattern.get", {"slot": 1})
    assert got["name"] == "ROUNDTRIP" and got["tempo"] == 132.0
    assert got["variations"]["A"]["BD"] == "X...x...X...x..."
    assert got["variations"]["A"]["CH"] == "xoxoxoxoxoxoxoxo"
    assert got["variations"]["B"]["SD"] == "....X.......X..."


def test_export_includes_melodies_as_notes(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "C", "instrument": "LT",
        "notes": "C3 . G3 D#3", "root": "C3"})
    doc = tools.call("pattern.export", {"slot": 0, "roots": {"LT": "C3"},
                                        "ctrl_is_coarse_tune": True})
    mel = doc["variations"]["C"]["melodies"]["LT"]
    assert mel["mode"] == "coarse" and mel["root"] == "C3"
    assert mel["notes"].startswith("C3 . G3 D#3")


def test_set_melody_states_both_panel_requirements(wired):
    """Neither is in the blob, so the tool has to say them out loud."""
    r = tools.call("pattern.set_melody", {
        "slot": 0, "variation": "C", "instrument": "LT",
        "notes": "C3 G3", "root": "C3"})
    setup = " ".join(r["panel_setup"])
    assert "MOTION" in setup and "CTRL" in setup and "LT" in setup

    fine = tools.call("pattern.set_melody", {
        "slot": 0, "variation": "D", "instrument": "LT",
        "notes": "C3 D3", "root": "C3", "mode": "fine"})
    # fine tune is byte +0, always Tune -- no CTRL assignment involved
    assert not any("CTRL" in s for s in fine["panel_setup"])


def test_export_will_not_read_ctrl_as_pitch_by_default(wired):
    """
    CTRL holds whatever is on that instrument's CTRL knob -- pan, a send, or
    Coarse Tune -- and the kit does not say which. Guessing turns a factory
    pattern's pan sweep into a melody in the tenth octave.
    """
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "C", "instrument": "LT",
        "notes": "C3 . G3 D#3", "root": "C3"})
    doc = tools.call("pattern.export", {"slot": 0, "roots": {"LT": "C3"}})
    mel = doc["variations"]["C"]["melodies"]["LT"]
    assert "notes" not in mel and mel["raw"], "CTRL was read as pitch unasked"
    assert "ctrl_is_coarse_tune" in mel["note"]


def test_import_restores_a_melody(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "D", "instrument": "LT",
        "notes": "C2 G2 C3", "root": "C2"})
    doc = tools.call("pattern.export", {"slot": 0, "roots": {"LT": "C2"}})
    tools.call("pattern.clear_variation", {"slot": 1, "variation": "D"})
    tools.call("pattern.import", {"slot": 1, "pattern": doc})
    back = tools.call("pattern.get_melody", {
        "slot": 1, "variation": "D", "instrument": "LT", "root": "C2"})
    assert back["melody"].startswith("C2 G2 C3")


def test_import_refuses_notes_without_a_root(wired):
    """A guessed root transposes the whole line, so skip and say so."""
    doc = {"variations": {"A": {"tracks": {"LT": "x..............."},
                                "melodies": {"LT": {"mode": "coarse",
                                                    "notes": "C3"}}}}}
    r = tools.call("pattern.import", {"slot": 1, "pattern": doc})
    assert any("without a root" in w for w in r["warnings"])


def test_import_is_partial_when_fields_are_missing(wired):
    before = tools.call("pattern.get", {"slot": 0})
    tools.call("pattern.import", {"slot": 0, "pattern": {"tempo": 100.0}})
    after = tools.call("pattern.get", {"slot": 0})
    assert after["tempo"] == 100.0
    assert after["name"] == before["name"], "an absent field must not be cleared"


# ------------------------------------------------------- single-note edits

def test_set_note_changes_one_step_only(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "E", "instrument": "LT",
        "notes": "C3 D3 E3 F3", "root": "C3"})
    before = tools.call("pattern.get_melody", {
        "slot": 0, "variation": "E", "instrument": "LT", "root": "C3"})["melody"]

    r = tools.call("pattern.set_note", {
        "slot": 0, "variation": "E", "instrument": "LT", "step": 3,
        "note": "A3", "root": "C3"})
    after = r["melody"].split()
    assert after[2] == "A3"
    assert after[:2] == before.split()[:2]
    assert after[3:] == before.split()[3:]


def test_set_note_preserves_hits_the_melody_never_touched(wired):
    """
    Re-sending a whole melody clears the instrument's other steps. Editing one
    note must not, or fixing a typo would silently delete drum hits.
    """
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "F", "instrument": "MT",
        "notes": "C3 . . .", "root": "C3"})
    tools.call("pattern.set_steps", {
        "slot": 0, "variation": "F", "instrument": "MT",
        "steps": "x......X........"})
    tools.call("pattern.set_note", {
        "slot": 0, "variation": "F", "instrument": "MT", "step": 1,
        "note": "D#3", "root": "C3"})
    steps = tools.call("pattern.get", {"slot": 0})["variations"]["F"]["MT"]
    assert steps[7] == "X", "an unrelated hit was wiped"


def test_set_note_gives_a_silent_step_a_hit(wired):
    tools.call("pattern.clear_variation", {"slot": 0, "variation": "G"})
    tools.call("pattern.set_note", {
        "slot": 0, "variation": "G", "instrument": "LT", "step": 5,
        "note": "G3", "root": "C3"})
    steps = tools.call("pattern.get", {"slot": 0})["variations"]["G"]["LT"]
    assert steps[4] != ".", "the note would never sound"


def test_set_note_null_clears_the_step(wired):
    tools.call("pattern.set_melody", {
        "slot": 0, "variation": "H", "instrument": "LT",
        "notes": "C3 D3 E3", "root": "C3"})
    tools.call("pattern.set_note", {
        "slot": 0, "variation": "H", "instrument": "LT", "step": 2,
        "note": None, "root": "C3"})
    p = Pattern.from_bytes(tools.device().transport.read_blob("pattern", 0))
    assert p.get_steps("H", "LT")[1] == "."
    assert p.get_motion("H", "LT", 1)["mask"] == 0


def test_set_note_refuses_what_coarse_tune_cannot_reach(wired):
    with pytest.raises(ToolError, match="outside Coarse Tune"):
        tools.call("pattern.set_note", {
            "slot": 0, "variation": "A", "instrument": "LT", "step": 1,
            "note": "C7", "root": "C3"})


def test_set_note_rejects_a_bad_note_or_root(wired):
    for bad in ({"note": "H9", "root": "C3"}, {"note": "C3", "root": "."}):
        with pytest.raises(ToolError):
            tools.call("pattern.set_note", {
                "slot": 0, "variation": "A", "instrument": "LT", "step": 1,
                **bad})


# ------------------------------------- the machine's kit-reference stamping

def test_a_kit_write_repairs_the_pattern_it_would_have_stamped(wired):
    """
    The machine writes the committed kit's index into byte 18 of the last
    pattern transferred. We hold the bytes we sent, so we send them again.
    """
    d = tools.device()
    tools.call("pattern.set_header", {"slot": 0, "kit": 10})
    sent_before = len(d.transport.sent)

    r = d.write_kit(61, d.read_kit(61))
    assert r.get("repaired_kit_reference_of") == 0
    # the repair is a real extra pattern transfer, not a no-op
    kinds = [k for k, _ in d.transport.sent[sent_before:]]
    assert kinds.count("pattern") == 1
    assert tools.call("pattern.get", {"slot": 0})["kit"] == 10


def test_the_repair_targets_the_last_pattern_written_not_all_of_them(wired):
    d = tools.device()
    tools.call("pattern.set_header", {"slot": 0, "kit": 10})
    tools.call("pattern.set_header", {"slot": 114, "kit": 11})
    r = d.write_kit(61, d.read_kit(61))
    assert r.get("repaired_kit_reference_of") == 114


def test_no_pattern_written_means_a_warning_not_silence(wired):
    """
    The machine remembers its last transfer across sessions; we do not. Some
    pattern was re-pointed and we cannot say which, so say that.
    """
    d = tools.device()
    d._last_pattern = None
    r = d.write_kit(61, d.read_kit(61))
    assert "repaired_kit_reference_of" not in r
    assert "could not be identified" in r["kit_reference_warning"]


def test_a_failed_repair_does_not_fail_the_kit_write(wired):
    """Losing the repair is bad; losing the kit write is worse."""
    d = tools.device()
    tools.call("pattern.set_header", {"slot": 0, "kit": 10})
    real = d.transport.send_blob

    def flaky(kind, slot, blob, **kw):
        if kind == "pattern":
            raise RuntimeError("the wire fell over")
        return real(kind, slot, blob, **kw)
    d.transport.send_blob = flaky
    r = d.write_kit(61, d.read_kit(61))
    assert r["committed"] is True
    assert "repaired_kit_reference_of" not in r


# ------------------------------------------ hotswapping while playing

def test_a_kit_can_be_changed_while_the_machine_plays(wired):
    """
    Reads hang during playback; writes do not (measured: 1.4s). Changing a
    sound mid-pattern is possible on the panel, so it must be possible here:
    serve the kit from the byte cache instead of refusing.
    """
    d = tools.device()
    tools.call("kit.get", {"slot": 0})               # warms the cache
    d.playing = lambda: True
    try:
        r = tools.call("kit.set_instrument", {"slot": 0, "instrument": "BD",
                                              "tone": 87})
        assert r["committed"] is True
        assert r.get("verified") is None, "it tried a read-back while playing"
        # the cache now holds the new tone, so a follow-up read agrees
        assert tools.call("kit.get", {"slot": 0})["instruments"]["BD"]["tone"] == 87
    finally:
        d.playing = None


def test_a_never_seen_kit_still_refuses_while_playing(wired):
    """No cached bytes means the only source is a read, which would hang."""
    d = tools.device()
    d.playing = lambda: True
    try:
        with pytest.raises(ToolError, match="never read yet"):
            tools.call("kit.get", {"slot": 61})
    finally:
        d.playing = None
