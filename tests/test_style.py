"""
Tests for the groove engine.

These assert musical properties, not exact strings — a generator that produced
one fixed pattern would pass a string comparison and be useless. What matters
is that techno lands on the floor, that energy adds layers in order, and that
a seed means the same bar twice.
"""

import pytest

from tr8s.style import (ACCENT, BACKBEAT, DOWNBEATS, GHOST, OFFBEAT_8, REST,
                        ROLES, STYLES, arrangement, describe, euclid, generate,
                        humanise, merge, place, thin)
import random


def hits(row):
    return {i for i, c in enumerate(row) if c != REST}


# ------------------------------------------------------------ rhythm tools

def test_euclid_spreads_evenly():
    assert euclid(4) == [0, 4, 8, 12]
    assert len(euclid(5)) == 5
    assert len(euclid(7)) == 7
    gaps = [b - a for a, b in zip(euclid(5), euclid(5)[1:])]
    assert max(gaps) - min(gaps) <= 1, "a euclidean rhythm is as even as it can be"


def test_euclid_never_lines_up_with_the_four():
    """That non-alignment is the whole reason hypnotic patterns work."""
    for pulses in (5, 7, 11):
        assert set(euclid(pulses)) != set(DOWNBEATS)


def test_euclid_rotation_and_edges():
    assert euclid(0) == []
    assert euclid(16) == list(range(16))
    assert euclid(4, rotate=2) == [2, 6, 10, 14]
    assert euclid(20) == list(range(16)), "more pulses than steps is clamped"


def test_merge_keeps_the_louder_hit():
    assert merge("o...", "X...")[0] == ACCENT
    assert merge("X...", "o...")[0] == ACCENT, "order must not matter"
    assert merge("....", "..x.")[2] == "x"


def test_thin_keeps_the_downbeats():
    rng = random.Random(1)
    row = place(range(16), "x")
    out = thin(row, 0.0, rng)                 # drop everything droppable
    assert hits(out) == set(DOWNBEATS)


def test_humanise_protects_what_carries_the_groove():
    """Softening the offbeat hats would remove the thing that makes it techno."""
    rng = random.Random(2)
    row = place(OFFBEAT_8, "x")
    out = humanise(row, rng, amount=1.0, protect=OFFBEAT_8)
    assert out == row
    # and without protection it really does demote
    assert humanise(row, random.Random(2), 1.0, protect=()) != row


# ---------------------------------------------------------------- generate

def test_every_style_generates_something_playable():
    for name in STYLES:
        g = generate(name, energy=0.7, seed=11)
        assert g["tracks"], f"{name} produced nothing"
        for inst, row in g["tracks"].items():
            assert len(row) == 16, f"{name}/{inst} is {len(row)} steps"
            assert set(row) <= set("Xxo."), f"{name}/{inst} has odd characters"
        lo, hi = STYLES[name].bpm
        assert lo <= g["tempo"] <= hi


def test_four_to_the_floor_styles_put_the_kick_on_the_floor():
    for name in ("techno", "hypnotic", "acid", "house", "hard", "lofi"):
        bd = generate(name, energy=0.6, seed=5)["tracks"]["BD"]
        assert set(DOWNBEATS) <= hits(bd), f"{name} lost the four"


def test_broken_and_dnb_do_not():
    """Their whole identity is that the kick is not on every beat."""
    for name in ("broken", "dnb"):
        bd = generate(name, energy=0.6, seed=5)["tracks"]["BD"]
        assert not set(DOWNBEATS) <= hits(bd), f"{name} is not broken"


def test_energy_adds_layers_rather_than_shuffling_them():
    quiet = generate("techno", energy=0.15, seed=9)["tracks"]
    loud = generate("techno", energy=0.95, seed=9)["tracks"]
    assert set(quiet) < set(loud), "raising energy must not remove a part"
    assert len(loud) > len(quiet) + 2


def test_the_open_hat_arrives_before_the_ride():
    """Layer order is what makes a rise read as a rise."""
    seen_oh = seen_rc = None
    for i in range(21):
        t = generate("techno", energy=i / 20, seed=4)["tracks"]
        if "OH" in t and seen_oh is None:
            seen_oh = i
        if "RC" in t and seen_rc is None:
            seen_rc = i
    assert seen_oh is not None and seen_rc is not None
    assert seen_oh < seen_rc


def test_hats_subdivide_as_energy_rises():
    counts = [len(hits(generate("techno", energy=e, seed=3)["tracks"]["CH"]))
              for e in (0.1, 0.4, 0.9)]
    assert counts[0] < counts[1] < counts[2]


def test_the_same_seed_gives_the_same_bar():
    a = generate("hypnotic", energy=0.5, seed=1234)
    b = generate("hypnotic", energy=0.5, seed=1234)
    assert a == b


def test_different_seeds_differ():
    rows = {tuple(sorted(generate("techno", energy=0.8, seed=s)["tracks"].items()))
            for s in range(6)}
    assert len(rows) > 1, "the seed is being ignored"


def test_a_seed_is_always_reported():
    g = generate("techno", seed=None)
    assert isinstance(g["seed"], int)
    assert generate("techno", seed=g["seed"])["tracks"] == g["tracks"]


def test_energy_is_clamped_not_rejected():
    assert generate("techno", energy=5)["energy"] == 1.0
    assert generate("techno", energy=-2)["energy"] == 0.0


def test_unknown_style_or_role_says_what_exists():
    with pytest.raises(ValueError, match="techno"):
        generate("gabber")
    with pytest.raises(ValueError, match="intro"):
        generate("techno", role="chorus")


# -------------------------------------------------------------------- roles

def test_a_break_takes_the_kick_away():
    assert "BD" not in generate("techno", energy=0.8, role="break", seed=2)["tracks"]


def test_a_drop_is_nearly_silent():
    t = generate("techno", energy=0.9, role="drop", seed=2)["tracks"]
    assert len(t) <= 2
    assert hits(t["BD"]) == {0}


def test_an_intro_is_a_subset_of_the_main_bar():
    intro = generate("techno", energy=0.6, role="intro", seed=8)["tracks"]
    main = generate("techno", energy=0.6, role="main", seed=8)["tracks"]
    assert set(intro) < set(main)


def test_a_fill_changes_the_end_of_the_bar():
    main = generate("techno", energy=0.7, role="main", seed=6)["tracks"]
    fill = generate("techno", energy=0.7, role="fill", seed=6)["tracks"]
    tail = lambda t: {k: v[12:] for k, v in t.items()}
    assert tail(fill) != tail(main)
    assert set(DOWNBEATS) <= hits(fill["BD"]), "a fill still keeps the floor"


def test_every_role_works_for_every_style():
    for name in STYLES:
        for role in ROLES:
            g = generate(name, energy=0.6, role=role, seed=1)
            assert isinstance(g["tracks"], dict)


# ------------------------------------------------------------- arrangement

def test_an_arrangement_fills_all_eight_variations():
    a = arrangement("techno", seed=42)
    assert set(a["variations"]) == set("ABCDEFGH")


def test_the_arrangement_has_the_shape_of_a_track():
    a = arrangement("techno", seed=42)["variations"]
    assert a["A"]["role"] == "intro"
    assert a["E"]["role"] == "break"
    assert a["G"]["energy"] > a["A"]["energy"], "it must build"
    assert a["E"]["energy"] < a["B"]["energy"], "the break must drop below the main"


def test_an_arrangement_is_reproducible():
    assert arrangement("dub", seed=7) == arrangement("dub", seed=7)


def test_describe_covers_every_style():
    d = describe()
    assert {x["name"] for x in d} == set(STYLES)
    for x in d:
        assert x["summary"] and x["kit_hint"]
