"""
Tests for tone-aware kit building.

Built against a synthetic catalogue rather than the real one, so the assertions
are about the selection rules and not about which tones this particular machine
happens to have.
"""

import pytest

from tr8s.kitbuild import (BASE, SCALES, STYLE_TARGETS, Target, build,
                           scale_pitches, score)
from tr8s.tones import Catalog, Tone


def tone(id, name, cat, centroid, decay=100, root=None, type=1,
         sustained=False, peak=0.5):
    return Tone(id=id, name=name, cat=cat, type=type, root=root, hz=None,
                cents=0, peak=peak, rms=0.2, decay_ms=decay,
                sustained=sustained, centroid=centroid)


def catalog(*tones) -> Catalog:
    c = Catalog.__new__(Catalog)
    c.tones = {t.id: t for t in tones}
    return c


def full_catalog():
    """One plausible candidate per track, plus decoys."""
    return catalog(
        tone(1, "Kick C", "BD", 90, 300, root="C1"),
        tone(2, "Kick F#", "BD", 95, 300, root="F#1"),
        tone(3, "Kick G", "BD", 92, 310, root="G1"),
        tone(10, "Snare", "SD", 1200, 90),
        tone(11, "Clap", "HC", 1500, 70),
        tone(12, "Rim", "RS", 1200, 40),
        tone(13, "CH", "CH/OH", 1800, 60),
        tone(14, "OH", "CH/OH", 1700, 350),
        tone(15, "Crash", "CC/RC", 1900, 700),
        tone(16, "Ride", "CC/RC", 1800, 500),
        tone(17, "Tom lo", "TOM", 200, 300),
        tone(18, "Tom mid", "TOM", 400, 250),
        tone(19, "Tom hi", "TOM", 600, 200),
        tone(20, "Bass", "BASS", 200, None, root="C2", type=2, sustained=True),
        tone(21, "Lead", "SYNTH1", 1000, None, root="C4", type=2, sustained=True),
    )


# ------------------------------------------------------------------ scales

def test_scale_pitches_reads_key_and_mode():
    tonic, scale = scale_pitches("C minor")
    assert tonic == 0
    assert scale == [0, 2, 3, 5, 7, 8, 10]


def test_mode_defaults_to_minor():
    assert scale_pitches("A")[1] == scale_pitches("A minor")[1]


def test_phrygian_has_the_flat_second():
    """The interval that makes it sound like techno rather than house."""
    tonic, scale = scale_pitches("F# phrygian")
    assert (tonic + 1) % 12 in scale


def test_unknown_key_or_mode_is_rejected():
    with pytest.raises(ValueError, match="mode"):
        scale_pitches("C klingon")
    with pytest.raises(ValueError, match="root"):
        scale_pitches("H minor")


# ------------------------------------------------------------------ scoring

def test_wrong_category_is_never_chosen():
    assert score(tone(1, "x", "SD", 1200), BASE["BD"]) < 0


def test_a_silent_tone_is_rejected_whatever_else_fits():
    t = tone(1, "x", "BD", 90, 300, peak=0.001)
    assert score(t, BASE["BD"]) < 0


def test_being_inside_the_window_beats_being_outside():
    inside = tone(1, "in", "BD", 90, 300)
    outside = tone(2, "out", "BD", 900, 800)
    assert score(inside, BASE["BD"]) > score(outside, BASE["BD"])


def test_a_tone_is_penalised_for_masking_something_already_chosen():
    t = tone(1, "hat", "CH/OH", 1800, 60)
    alone = score(t, BASE["CH"])
    crowded = score(t, BASE["CH"], taken_centroids=[1810])
    assert crowded < alone


def test_sustain_and_type_are_hard_requirements():
    target = Target(("BASS",), sustained=True, type_=2)
    assert score(tone(1, "b", "BASS", 200, type=2, sustained=True), target) > 0
    assert score(tone(2, "b", "BASS", 200, type=2, sustained=False), target) < 0
    assert score(tone(3, "b", "BASS", 200, type=1, sustained=True), target) < 0


# -------------------------------------------------------------------- build

def test_every_track_gets_a_tone():
    p = build("techno", "C minor", seed=1, catalog=full_catalog())
    assert set(p["instruments"]) == set(BASE)


def test_the_kick_is_chosen_to_agree_with_the_key():
    """A kick a semitone off the key beats against the bass on every downbeat."""
    for key, want in (("C minor", "C1"), ("F# minor", "F#1")):
        p = build("techno", key, seed=1, catalog=full_catalog())
        assert p["instruments"]["BD"]["root"] == want, key
        assert "tonic" in p["instruments"]["BD"]["why"]


def test_the_fifth_is_accepted_when_the_tonic_is_missing():
    c = catalog(*[t for t in full_catalog().tones.values() if t.id != 1])
    p = build("techno", "C minor", seed=1, catalog=c)
    assert p["instruments"]["BD"]["root"] == "G1"
    assert "fifth" in p["instruments"]["BD"]["why"]


def test_melodic_tracks_get_sustained_sample_tones():
    p = build("techno", "C minor", seed=1, catalog=full_catalog())
    for track in p["melodic_tracks"]:
        inst = p["instruments"][track]
        assert inst["sustained"], f"{track} cannot hold a note"


def test_a_style_changes_what_is_chosen():
    """lofi wants a darker hat than techno; the plan must reflect that."""
    assert STYLE_TARGETS["lofi"]["CH"].centroid != BASE["CH"].centroid
    c = catalog(
        tone(1, "Kick", "BD", 90, 300, root="C1"),
        tone(13, "bright hat", "CH/OH", 1800, 60),
        tone(14, "dark hat", "CH/OH", 1100, 60),
    )
    assert build("techno", "C minor", seed=1,
                 catalog=c)["instruments"]["CH"]["tone"] == 13
    assert build("lofi", "C minor", seed=1,
                 catalog=c)["instruments"]["CH"]["tone"] == 14


def test_every_style_and_mode_builds():
    c = full_catalog()
    for style in list(STYLE_TARGETS):
        for mode in SCALES:
            p = build(style, f"C {mode}", seed=3, catalog=c)
            assert p["instruments"]


def test_a_seed_is_reported_and_reproduces():
    p = build("techno", "C minor", seed=None, catalog=full_catalog())
    assert isinstance(p["seed"], int)
    again = build("techno", "C minor", seed=p["seed"], catalog=full_catalog())
    assert again["instruments"] == p["instruments"]


def test_an_empty_catalogue_says_what_to_run():
    with pytest.raises(ValueError, match="analyse-tones"):
        build("techno", "C minor", catalog=catalog())


def test_every_choice_explains_itself():
    p = build("techno", "C minor", seed=1, catalog=full_catalog())
    for track, inst in p["instruments"].items():
        assert inst["why"], f"{track} was chosen for no stated reason"


# ----------------------------------------------------------- the register

def register_catalog():
    """The same oscillator at four octaves, which is what the machine has."""
    return catalog(
        tone(1, "Kick", "BD", 90, 300, root="C1"),
        tone(50, "OSC Saw Low", "SYNTH2", 700, None, root="C2", type=2,
             sustained=True),
        tone(51, "OSC Saw Mid", "SYNTH2", 700, None, root="C4", type=2,
             sustained=True),
        tone(52, "OSC Saw High", "SYNTH2", 700, None, root="C5", type=2,
             sustained=True),
    )


def test_the_bass_track_gets_a_low_rooted_tone():
    """
    Brightness cannot tell C2 from C5: the machine offers the same oscillator
    at four octaves. Chosen on centroid alone, a "bassline" lands in the fifth.
    """
    for seed in range(8):
        p = build("techno", "C minor", seed=seed, catalog=register_catalog())
        bass = p["instruments"][p["melodic_tracks"][0]]
        assert bass["root"] == "C2", f"seed {seed} put the bass at {bass['root']}"


def test_a_root_outside_the_register_is_called_out():
    """If only a high tone exists, take it — but say what will happen."""
    c = catalog(
        tone(1, "Kick", "BD", 90, 300, root="C1"),
        tone(52, "OSC Saw High", "SYNTH2", 700, None, root="C5", type=2,
             sustained=True),
    )
    p = build("techno", "C minor", seed=1, catalog=c)
    bass = p["instruments"][p["melodic_tracks"][0]]
    assert bass["root"] == "C5"
    assert "WARNING" in bass["why"] and "wrong octave" in bass["why"]


def test_the_lead_sits_above_the_bass():
    p = build("techno", "C minor", seed=2, catalog=register_catalog())
    tracks = p["melodic_tracks"]
    if len(tracks) < 2:
        pytest.skip("only one melodic track was placed")
    from tr8s.melody import note_to_midi
    bass, lead = (p["instruments"][t] for t in tracks[:2])
    assert note_to_midi(lead["root"]) > note_to_midi(bass["root"])


def test_no_two_instruments_share_a_tone():
    """Two tracks on the identical sound is a wasted voice."""
    for seed in range(10):
        p = build("techno", "C minor", seed=seed, catalog=full_catalog())
        ids = [v["tone"] for v in p["instruments"].values()]
        assert len(ids) == len(set(ids)), f"seed {seed} reused a tone"
