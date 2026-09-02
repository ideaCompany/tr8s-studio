"""
Changing a sound by description. Built on a synthetic catalogue so the
assertions are about the ranking rules, not this machine's library.
"""

import pytest

from tr8s.swap import by_description, neighbours, parse
from tr8s.tones import Catalog, Tone


def tone(id, name, cat, centroid, decay=100, hz=100.0, peak=0.5, sustained=False):
    return Tone(id=id, name=name, cat=cat, type=1, root=None, hz=hz, cents=0,
                peak=peak, rms=0.2, decay_ms=decay, sustained=sustained,
                centroid=centroid)


def catalog(*tones):
    c = Catalog.__new__(Catalog)
    c.tones = {t.id: t for t in tones}
    return c


KICKS = catalog(
    tone(1, "mid kick", "BD", 100, decay=300, hz=60),
    tone(2, "dark kick", "BD", 60, decay=300, hz=55),
    tone(3, "bright kick", "BD", 180, decay=300, hz=70),
    tone(4, "short kick", "BD", 100, decay=120, hz=60),
    tone(5, "long kick", "BD", 100, decay=700, hz=60),
    tone(6, "dark short kick", "BD", 65, decay=110, hz=58),
    tone(9, "a snare", "SD", 1200, decay=80, hz=200),
)


def test_parse_understands_direction_and_amount():
    assert parse("darker") == [("centroid", -1, 0.5)]
    assert parse("a bit brighter") == [("centroid", +1, 0.25)]
    assert parse("much shorter, slightly lower") == [
        ("decay_ms", -1, 0.8), ("hz", -1, 0.15)]


def test_parse_ignores_what_it_does_not_know():
    assert parse("make it funkier") == []


def test_darker_returns_only_darker_and_nearest_first():
    r = by_description(KICKS, 1, "darker")
    names = [c["name"] for c in r["candidates"]]
    assert names[0] == "dark kick"
    assert "bright kick" not in names, "moved the wrong way"
    assert all(c["centroid"] < 100 for c in r["candidates"])


def test_two_axes_must_both_move_the_right_way():
    r = by_description(KICKS, 1, "darker and shorter")
    names = [c["name"] for c in r["candidates"]]
    assert names == ["dark short kick"]


def test_stays_in_category_unless_told_otherwise():
    r = by_description(KICKS, 1, "brighter")
    assert all(c["category"] == "BD" for c in r["candidates"])
    r2 = by_description(KICKS, 1, "brighter", same_category=False)
    assert any(c["category"] == "SD" for c in r2["candidates"])


def test_an_unknown_description_says_what_it_understands():
    r = by_description(KICKS, 1, "funkier")
    assert "error" in r and "darker/brighter" in r["error"]


def test_nothing_in_that_direction_is_reported_not_faked():
    r = by_description(KICKS, 2, "darker")           # already the darkest
    assert r["candidates"] == []
    assert r["note"] and "moves that way" in r["note"]


def test_neighbours_are_nearest_first_and_exclude_self():
    ns = [t.name for t in neighbours(KICKS, 1, limit=3)]
    assert "mid kick" not in ns
    assert ns[0] in ("short kick", "dark kick", "long kick", "bright kick")
    assert len(ns) == 3


def test_neighbours_of_an_unknown_tone_is_empty():
    assert neighbours(KICKS, 999) == []


def test_a_sustained_tone_counts_as_longest():
    c = catalog(tone(1, "hit", "BD", 100, decay=200),
                tone(2, "pad", "BD", 100, decay=None, sustained=True))
    r = by_description(c, 1, "longer")
    assert [x["name"] for x in r["candidates"]] == ["pad"]
