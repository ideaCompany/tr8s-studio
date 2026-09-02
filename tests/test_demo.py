"""
Tests for the offline TR-8S.

Its value is that it behaves like the real machine in the ways that bit us, so
these check the behaviours rather than the content: writes land immediately,
level is taken over by the faders, and a kit is self-consistent about which
tracks can actually play a melody.
"""

import pytest

from tr8s import demo, tools
from tr8s.kit import Kit
from tr8s.melody import note_to_midi
from tr8s.pattern import Pattern
from tr8s.transport import BLOB_SIZES


@pytest.fixture
def offline():
    t = demo.install()
    yield t
    tools.set_device(None)


def test_every_demo_pattern_reads_back(offline):
    for slot, spec in demo.DEMO_PATTERNS.items():
        p = tools.call("pattern.get", {"slot": slot})
        assert p["name"] == spec["name"]
        assert p["tempo"] == spec["tempo"]
        assert p["shuffle"] == 0, "a blank blob reads as -128 unless seeded"
        for v, tracks in spec["variations"].items():
            got = p["variations"][v]
            for inst, steps in tracks.items():
                assert got[inst] == steps, f"{slot} {v} {inst}"


def test_a_write_lands_in_the_slot_immediately(offline):
    """There is no scratch buffer on the real machine; there is none here."""
    slot = demo.default_slot()
    tools.call("pattern.set_steps", {"slot": slot, "variation": "A",
                                     "instrument": "RC", "steps": "X" * 16})
    assert tools.call("pattern.get", {"slot": slot})["variations"]["A"]["RC"] \
        == "X" * 16


def test_level_is_taken_over_by_the_faders(offline):
    slot = demo.DEMO_PATTERNS[demo.default_slot()]["kit"]
    k = Kit.from_bytes(offline.read_blob("kit", slot))
    blob = bytearray(k.to_bytes())
    blob[Kit.record_offset("BD") + 4] = 3          # try to set a tiny level
    offline.send_blob("kit", slot, bytes(blob))
    back = Kit.from_bytes(offline.read_blob("kit", slot))
    assert back.get("BD", "level") == demo.FADER_LEVEL, "level was writable"


def test_melodic_tracks_have_the_sample_parameters_they_need(offline):
    """
    A sample tone on a record with no sample parameters is the bug that made
    real instruments almost inaudible. The demo must not reproduce it.
    """
    slot = demo.DEMO_PATTERNS[demo.default_slot()]["kit"]
    k = Kit.from_bytes(offline.read_blob("kit", slot))
    for inst in demo.MELODIC:
        assert k.has_sample_params(inst), f"{inst} would be nearly silent"


def test_demo_melodies_are_within_coarse_tune_range(offline):
    """A note more than two octaves off the root would be clamped silently."""
    root = note_to_midi(demo.MELODIC_ROOT)
    for spec in demo.DEMO_PATTERNS.values():
        mel = spec.get("melody")
        if not mel:
            continue
        for tok in mel[2].split():
            if tok == ".":
                continue
            assert abs(note_to_midi(tok) - root) <= 24, f"{tok} is out of reach"


def test_melodies_read_back_as_written(offline):
    for slot, spec in demo.DEMO_PATTERNS.items():
        mel = spec.get("melody")
        if not mel:
            continue
        v, inst, notes, root = mel
        got = tools.call("pattern.get_melody",
                         {"slot": slot, "variation": v, "instrument": inst,
                          "root": root})["melody"]
        assert got.split()[:len(notes.split())] == notes.split()


def test_unwritten_slots_read_as_missing(offline):
    assert offline.read_blob("pattern", 7) is None
    assert offline.read_blob("kit", 7) is None


def test_a_wrong_sized_blob_is_refused(offline):
    with pytest.raises(ValueError, match="bytes"):
        offline.send_blob("pattern", 0, b"\x00" * 10)


def test_blobs_are_the_documented_sizes(offline):
    slot = demo.default_slot()
    assert len(offline.read_blob("pattern", slot)) == BLOB_SIZES["pattern"]
    kit = demo.DEMO_PATTERNS[slot]["kit"]
    assert len(offline.read_blob("kit", kit)) == BLOB_SIZES["kit"]


def test_demo_tones_cover_every_track():
    from tr8s.kit import TRACKS
    assert set(demo.DEMO_TONES_BY_TRACK) == set(TRACKS)
