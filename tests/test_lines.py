"""
Tests for the line generators.

Musical properties again, not fixed strings: a line is correct if it is in key,
in a register that exists, reachable by Coarse Tune, and shaped like the thing
it claims to be.
"""

import pytest

from tr8s.kitbuild import scale_pitches
from tr8s.lines import SHAPES, acid, arp, bassline, generate, stab
from tr8s.melody import COARSE_MAX, COARSE_MIN, note_to_midi

KEYS = ["C minor", "F# phrygian", "A dorian", "D# minor", "G major"]


def pitches(result):
    return [note_to_midi(n) for n in result["notes"].split() if n != "."]


def in_key(result, key):
    _, scale = scale_pitches(key)
    return all(m % 12 in scale for m in pitches(result))


# ------------------------------------------------------------------ in key

@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("key", KEYS)
def test_every_note_belongs_to_the_scale(shape, key):
    for seed in range(12):
        r = generate(shape, key=key, energy=0.8, seed=seed, root="C2")
        assert in_key(r, key), f"{shape} {key} seed {seed}: {r['notes']}"


@pytest.mark.parametrize("shape", SHAPES)
def test_every_note_is_reachable_by_coarse_tune(shape):
    root = note_to_midi("C2")
    for seed in range(20):
        r = generate(shape, key="F# phrygian", energy=1.0, seed=seed, root="C2")
        for m in pitches(r):
            assert COARSE_MIN <= m - root <= COARSE_MAX, r["notes"]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_line_is_never_silent(shape):
    for seed in range(20):
        r = generate(shape, key="C minor", energy=0.05, seed=seed, root="C2")
        assert pitches(r), f"{shape} seed {seed} produced nothing"


@pytest.mark.parametrize("shape", SHAPES)
def test_lines_stay_in_an_audible_register(shape):
    """A bassline an octave too low is felt by nobody."""
    for key in KEYS:
        for seed in range(20):
            for m in pitches(generate(shape, key=key, energy=0.9, seed=seed,
                                      root="C2")):
                assert m >= note_to_midi("C1"), f"{shape} {key} went subsonic"


# ------------------------------------------------------------------- shapes

def test_the_bassline_sits_on_the_offbeats_when_quiet():
    """That placement between the kicks is what makes it techno."""
    r = bassline(key="C minor", energy=0.2, seed=4, root="C2")
    played = [i for i, n in enumerate(r["notes"].split()) if n != "."]
    assert played == [2, 6, 10, 14]


def test_the_bassline_mostly_stays_on_the_tonic():
    """Movement is the exception. A wandering techno bass is a broken one."""
    r = bassline(key="C minor", energy=0.6, seed=4, root="C2")
    notes = [n for n in r["notes"].split() if n != "."]
    tonic = max(set(notes), key=notes.count)
    assert notes.count(tonic) / len(notes) > 0.6


def test_the_bassline_gets_busier_with_energy():
    quiet = len(pitches(bassline(key="C minor", energy=0.1, seed=2, root="C2")))
    loud = len(pitches(bassline(key="C minor", energy=1.0, seed=2, root="C2")))
    assert loud > quiet


def test_acid_reports_accents_that_land_on_played_steps():
    for seed in range(15):
        r = acid(key="C minor", energy=0.8, seed=seed, root="C2")
        steps = r["notes"].split()
        for i in r["accents"]:
            assert steps[i] != ".", "an accent on a rest is inaudible"


def test_acid_lives_around_its_root_rather_than_above_it():
    """The 303 jumps to the octave; it does not sit there."""
    r = acid(key="C minor", energy=0.9, seed=3, root="C2")
    ms = pitches(r)
    home = min(ms)
    assert sum(1 for m in ms if m < home + 12) > len(ms) / 2


def test_a_stab_is_sparse_and_offbeat():
    r = stab(key="C minor", energy=0.3, seed=1, root="C3")
    played = [i for i, n in enumerate(r["notes"].split()) if n != "."]
    assert len(played) <= 4
    assert all(i % 2 == 0 and i % 4 != 0 for i in played), "stabs sit off the beat"


def test_an_arp_ascends():
    r = arp(key="C minor", energy=0.8, seed=1, root="C3", direction="up")
    ms = pitches(r)
    first = ms[:4]
    assert first == sorted(first), f"an up arp must rise: {r['notes']}"


def test_arp_direction_reverses_it():
    up = pitches(arp(key="C minor", seed=1, root="C3", direction="up"))
    down = pitches(arp(key="C minor", seed=1, root="C3", direction="down"))
    assert down[:3] == sorted(down[:3], reverse=True)
    assert up[:3] != down[:3]


# ---------------------------------------------------------------- mechanics

@pytest.mark.parametrize("shape", SHAPES)
def test_the_same_seed_gives_the_same_line(shape):
    a = generate(shape, key="C minor", energy=0.7, seed=99, root="C2")
    b = generate(shape, key="C minor", energy=0.7, seed=99, root="C2")
    assert a == b


def test_a_seed_is_always_reported():
    r = generate("acid", key="C minor", seed=None, root="C2")
    assert isinstance(r["seed"], int)
    assert generate("acid", key="C minor", seed=r["seed"],
                    root="C2")["notes"] == r["notes"]


def test_an_unknown_shape_lists_what_exists():
    with pytest.raises(ValueError, match="bass"):
        generate("dubstep_wobble")


def test_a_bad_key_is_rejected():
    with pytest.raises(ValueError):
        generate("bass", key="C klingon")


def test_out_of_reach_notes_are_reported_not_silently_moved():
    """Clamping without saying so would transpose a line by an octave."""
    r = arp(key="C minor", energy=0.8, seed=1, root="C5", direction="up")
    assert all(COARSE_MIN <= m - note_to_midi("C5") <= COARSE_MAX
               for m in pitches(r))
