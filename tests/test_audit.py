"""
Tests for the pattern critic.

Synthetic tones throughout: the point is the rules, not this machine's library.
A critic that fires on everything is worse than none, so several of these check
that it stays quiet.
"""

import pytest

from tr8s.audit import LOW_HZ, METAL, audit, step_ms
from tr8s.kit import Kit
from tr8s.pattern import Pattern
from tr8s.tones import Catalog, Tone
from tr8s.transport import BLOB_SIZES


def tone(id, name, centroid, decay=100, sustained=False, root=None):
    return Tone(id=id, name=name, cat="X", type=2, root=root, hz=None, cents=0,
                peak=0.5, rms=0.2, decay_ms=decay, sustained=sustained,
                centroid=centroid)


def setup(tracks, tones, tempo=140.0):
    """tracks: {inst: (steps, tone_id)}; tones: list of Tone."""
    p = Pattern.from_bytes(bytes(BLOB_SIZES["pattern"]))
    p.tempo = tempo
    p.scale = "16"          # a blank blob reads as 8T, which changes step_ms
    k = Kit.from_bytes(bytes(BLOB_SIZES["kit"]))
    for inst, (steps, tid) in tracks.items():
        p.set_steps("A", inst, steps)
        k.set(inst, "tone", tid)
    c = Catalog.__new__(Catalog)
    c.tones = {t.id: t for t in tones}
    return p, k, c


def kinds(r):
    return {f["kind"] for f in r["findings"]}


# ------------------------------------------------------------------- timing

def test_step_ms_matches_the_arithmetic():
    assert round(step_ms(140), 1) == 107.1        # a 16th at 140 BPM
    assert round(step_ms(120), 1) == 125.0
    assert step_ms(140, "32") < step_ms(140, "16")


# ----------------------------------------------------------- the low end

def test_two_low_sounds_on_the_same_step_are_a_warning():
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "LT": ("X...X...........", 2)},
        [tone(1, "Kick", 90), tone(2, "Bass", 120, sustained=True)])
    r = audit(p, k, c)
    low = [f for f in r["findings"] if f["kind"] == "low-end collision"]
    assert low and low[0]["severity"] == "warning"
    assert low[0]["steps"] == [1, 5]


def test_a_bassline_between_the_kicks_is_not_flagged():
    """The correct arrangement must not produce a finding."""
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "LT": ("..x...x...x...x.", 2)},
        [tone(1, "Kick", 90), tone(2, "Bass", 120, sustained=True)])
    assert "low-end collision" not in kinds(audit(p, k, c))


def test_a_low_sound_against_a_high_one_is_fine():
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "CH": ("X...X...X...X...", 2)},
        [tone(1, "Kick", 90), tone(2, "Hat", 1800, decay=40)])
    assert "low-end collision" not in kinds(audit(p, k, c))


# ---------------------------------------------------------------- masking

def test_two_parts_at_the_same_brightness_are_reported():
    p, k, c = setup(
        {"SD": ("....X.......X...", 1), "RS": ("....X.......X...", 2)},
        [tone(1, "Snare", 1200), tone(2, "Rim", 1250)])
    assert "masking" in kinds(audit(p, k, c))


def test_metal_is_never_reported_as_masking_metal():
    """
    Brightness is measured on audio decimated to 6 kHz, so hats and cymbals all
    land in the same band. A finding that fires on every kit is not a finding.
    """
    assert {"CH", "OH", "CC", "RC"} == METAL
    p, k, c = setup(
        {"CH": ("xxxxxxxxxxxxxxxx", 1), "RC": ("x.x.x.x.x.x.x.x.", 2)},
        [tone(1, "Hat", 1865, decay=40), tone(2, "Ride", 1915, decay=60)])
    assert "masking" not in kinds(audit(p, k, c))


def test_parts_that_never_coincide_do_not_mask():
    p, k, c = setup(
        {"SD": ("X...............", 1), "RS": (".......X........", 2)},
        [tone(1, "Snare", 1200), tone(2, "Rim", 1210)])
    assert "masking" not in kinds(audit(p, k, c))


# --------------------------------------------------------------- smearing

def test_a_tone_longer_than_its_own_gap_is_reported():
    p, k, c = setup(
        {"OH": ("x.x.x.x.x.x.x.x.", 1)},
        [tone(1, "Long hat", 1700, decay=900)], tempo=140)
    f = [x for x in audit(p, k, c)["findings"] if x["kind"] == "smearing"]
    assert f and f[0]["severity"] == "warning"


def test_a_short_tone_at_the_same_spacing_is_not():
    p, k, c = setup(
        {"CH": ("xxxxxxxxxxxxxxxx", 1)},
        [tone(1, "Tight hat", 1800, decay=40)], tempo=140)
    assert "smearing" not in kinds(audit(p, k, c))


def test_tempo_decides_whether_a_tone_smears():
    """The same tone is fine slow and muddy fast."""
    tones = [tone(1, "Hat", 1700, decay=350)]
    tracks = {"CH": ("x.x.x.x.x.x.x.x.", 1)}
    slow = audit(*setup(tracks, tones, tempo=90))
    fast = audit(*setup(tracks, tones, tempo=175))
    assert "smearing" not in kinds(slow)
    assert "smearing" in kinds(fast)


def test_a_sustained_tone_is_noted_but_not_alarming():
    p, k, c = setup({"LT": ("x...x...x...x...", 1)},
                    [tone(1, "Pad", 400, sustained=True)])
    f = [x for x in audit(p, k, c)["findings"] if x["kind"] == "smearing"]
    assert f and f[0]["severity"] == "info"


# --------------------------------------------------------------- registers

def test_a_loop_with_no_low_end_is_a_warning():
    p, k, c = setup({"CH": ("xxxxxxxxxxxxxxxx", 1)},
                    [tone(1, "Hat", 1800, decay=40)])
    f = [x for x in audit(p, k, c)["findings"] if x["kind"] == "register"]
    assert any(x["severity"] == "warning" for x in f)


def test_a_loop_with_no_top_end_is_only_an_observation():
    p, k, c = setup({"BD": ("X...X...X...X...", 1)},
                    [tone(1, "Kick", 90, decay=100)])
    f = [x for x in audit(p, k, c)["findings"]
         if x["kind"] == "register" and "1 kHz" in x["detail"]]
    assert f and f[0]["severity"] == "info"


def test_a_complete_loop_raises_no_register_finding():
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "CH": ("..x...x...x...x.", 2)},
        [tone(1, "Kick", 90, decay=100), tone(2, "Hat", 1800, decay=40)])
    assert "register" not in kinds(audit(p, k, c))


# ------------------------------------------------------------ bookkeeping

def test_an_empty_variation_says_so():
    p, k, c = setup({}, [])
    r = audit(p, k, c)
    assert r["parts"] == [] and "nothing plays" in r["verdict"]


def test_unmeasured_tones_are_listed_not_guessed_at():
    p, k, c = setup({"BD": ("X...X...X...X...", 99)}, [tone(1, "Kick", 90)])
    r = audit(p, k, c)
    assert r["unmeasured"] == [{"instrument": "BD", "tone": 99}]
    assert r["parts"] == []


def test_warnings_are_reported_before_observations():
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "LT": ("X...X...X...X...", 2),
         "CH": ("xxxxxxxxxxxxxxxx", 3)},
        [tone(1, "Kick", 90), tone(2, "Bass", 120, sustained=True),
         tone(3, "Hat", 1800, decay=40)])
    sev = [f["severity"] for f in audit(p, k, c)["findings"]]
    assert sev == sorted(sev, key=lambda s: 0 if s == "warning" else 1)


def test_the_verdict_names_the_problem_when_there_is_one():
    p, k, c = setup(
        {"BD": ("X...X...X...X...", 1), "LT": ("X...X...X...X...", 2)},
        [tone(1, "Kick", 90), tone(2, "Bass", 120, sustained=True)])
    assert "low-end collision" in audit(p, k, c)["verdict"]


# --------------------------------------------------- lines are not drums

def test_a_melodic_part_is_never_flagged_as_smearing():
    """
    A bassline note that rings until the next one is legato. Reading it as a
    muddy drum part is the audit misunderstanding what the track is.
    """
    from tr8s.melody import write as melody_write
    p, k, c = setup({"LT": ("x.x.x.x.x.x.x.x.", 1)},
                    [tone(1, "Bass", 200, decay=900, root="C2")], tempo=140)
    melody_write(p, "A", "LT", "C2 D2 E2 F2 G2 A2 B2 C3", "C2", mode="coarse")
    r = audit(p, k, c)
    assert "smearing" not in kinds(r)
    assert next(x for x in r["parts"] if x["instrument"] == "LT")["melodic"]


def test_the_same_part_without_motion_is_still_flagged():
    p, k, c = setup({"LT": ("x.x.x.x.x.x.x.x.", 1)},
                    [tone(1, "Tom", 200, decay=900)], tempo=140)
    assert "smearing" in kinds(audit(p, k, c))


def test_the_kit_envelope_shortens_what_the_audit_sees():
    """
    kit.fix shortens DECAY. If the audit only reads the tone's catalogue
    length it reports the same problem forever and the fix looks broken.
    """
    from tr8s.calibration import decay_byte_for_ms
    p, k, c = setup({"OH": ("x.x.x.x.x.x.x.x.", 1)},
                    [tone(1, "Long hat", 1700, decay=900)], tempo=140)
    assert "smearing" in kinds(audit(p, k, c))
    k.set("OH", "decay", decay_byte_for_ms(80))
    assert "smearing" not in kinds(audit(p, k, c))
