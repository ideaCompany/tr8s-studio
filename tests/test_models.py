"""
Offline tests. No hardware required: the models are pure functions over blobs,
and real blobs captured from the device are used as fixtures where available.
"""

import struct

import pytest

from tr8s import melody as M
from tr8s.kit import Kit, KitError
from tr8s.pattern import BLOCK, HEADER, SIZE, Pattern, PatternError
from tr8s.transport import (checksum, decode7, encode7, make_sysex,
                            offset_address, pack7, split_sysex, unpack7)


# ------------------------------------------------------------------ transport

def test_seven_bit_address_roundtrip():
    for v in (0, 1, 127, 128, 16383, 167772160, 167772298):
        assert decode7(encode7(v, 4)) == v


def test_offset_address_carries_across_bytes():
    # utility base 50 00 00 00 plus 0x41 stays inside the low byte
    assert offset_address([0x50, 0, 0, 0], 0x41) == [0x50, 0x00, 0x00, 0x41]
    # +138 must carry into the third byte, not overflow the fourth
    assert offset_address([0x50, 0, 0, 0], 138) == [0x50, 0x00, 0x01, 0x0A]


def test_checksum_matches_known_good_message():
    """A community-documented variation-select message, byte for byte."""
    known = bytes.fromhex("f0411000000045122010004100010ef7".replace(" ", ""))
    mine = make_sysex(0x12, [0x20, 0x10, 0x00, 0x41], [0x00, 0x01])
    assert mine == known


def test_checksum_formula():
    payload = [0x50, 0x00, 0x00, 0x13, 0x00]
    assert checksum(payload) == 0x1D


def test_pack_unpack_roundtrip():
    import os
    data = os.urandom(1000)
    assert unpack7(pack7(data))[:1000] == data


def test_pack7_strips_high_bits_into_header():
    packed = pack7(bytes([0xFF] * 7))
    assert packed[0] == 0b1111111
    assert all(b == 0x7F for b in packed[1:])


def test_split_sysex_finds_messages():
    a = make_sysex(0x12, [0x50, 0, 0, 0x13], [0])
    b = make_sysex(0x12, [0x50, 0, 0, 0x14], [0])
    assert split_sysex(a + b) == [a, b]
    # realtime bytes interleaved between messages are ignored by the splitter
    assert split_sysex(a + bytes([0xF8]) + b) == [a, b]


# -------------------------------------------------------------------- pattern

def blank_pattern() -> Pattern:
    raw = bytearray(SIZE)
    raw[0:16] = b"TEST            "
    struct.pack_into("<H", raw, 16, 1260)
    raw[18] = 1
    raw[19] = 2
    raw[32] = 128
    return Pattern(raw)


def test_pattern_rejects_wrong_size():
    with pytest.raises(PatternError):
        Pattern(bytearray(100))


def test_pattern_header_roundtrip():
    p = blank_pattern()
    assert p.name == "TEST"
    assert p.tempo == 126.0
    assert p.kit == 0
    assert p.scale == "16"
    assert p.shuffle == 0
    p.name = "MELODIC"
    p.tempo = 174.0
    p.kit = 61
    p.scale = "32"
    p.shuffle = -40
    assert (p.name, p.tempo, p.kit, p.scale, p.shuffle) == \
           ("MELODIC", 174.0, 61, "32", -40)


def test_tempo_is_tenths_of_a_bpm():
    p = blank_pattern()
    p.tempo = 134.0
    assert struct.unpack_from("<H", p.raw, 16)[0] == 1340


def test_kit_reference_is_one_based_on_the_wire():
    p = blank_pattern()
    p.kit = 122               # panel shows 123
    assert p.raw[18] == 123


def test_shuffle_is_offset_binary():
    p = blank_pattern()
    p.shuffle = 100
    assert p.raw[32] == 228   # 0x80 + 100, as the panel diff showed
    p.shuffle = -128
    assert p.raw[32] == 0


def test_header_validation():
    p = blank_pattern()
    for bad in (39.0, 301.0):
        with pytest.raises(PatternError):
            p.tempo = bad
    with pytest.raises(PatternError):
        p.kit = 128
    with pytest.raises(PatternError):
        p.scale = "7"
    with pytest.raises(PatternError):
        p.shuffle = 200


def test_steps_roundtrip_and_velocities():
    p = blank_pattern()
    p.set_steps("A", "BD", "X...x...o...X...")
    assert p.get_steps("A", "BD") == "X...x...o...X..."
    off = Pattern._inst_offset(0, "BD", 0)
    assert p.raw[off] == 112          # X
    assert p.raw[off + 4 * 4] == 100  # x
    assert p.raw[off + 8 * 4] == 55   # o


def test_steps_pad_to_sixteen():
    p = blank_pattern()
    p.set_steps("A", "CH", "x.x.")
    assert p.get_steps("A", "CH") == "x.x............."


def test_steps_reject_bad_input():
    p = blank_pattern()
    with pytest.raises(PatternError):
        p.set_steps("A", "BD", "X" * 17)
    with pytest.raises(PatternError):
        p.set_steps("A", "BD", "XyZ.")
    with pytest.raises(PatternError):
        p.set_steps("A", "XX", "X...")
    with pytest.raises(PatternError):
        p.set_steps("Z", "BD", "X...")


def test_variations_are_independent():
    p = blank_pattern()
    p.set_steps("A", "BD", "X...............")
    p.set_steps("B", "BD", "....X...........")
    assert p.get_steps("A", "BD") == "X..............."
    assert p.get_steps("B", "BD") == "....X..........."


def test_variation_block_geometry():
    """Ten blocks of 2436 must exactly fill the blob after the header."""
    assert (SIZE - HEADER) % BLOCK == 0
    assert (SIZE - HEADER) // BLOCK == 10


def test_instrument_tracks_do_not_collide_with_motion_lanes():
    p = blank_pattern()
    p.set_steps("A", "RC", "X" * 16)          # last instrument track, index 10
    p.set_motion("A", "BD", 0, tune=64)       # first motion lane, index 12
    assert p.get_steps("A", "RC") == "X" * 16
    assert p.get_motion("A", "BD", 0)["tune"] == 64


def test_motion_presence_mask():
    p = blank_pattern()
    assert p.get_motion("A", "LT", 3)["mask"] == 0
    p.set_motion("A", "LT", 3, tune=-24)
    m = p.get_motion("A", "LT", 3)
    assert m["tune"] == -24 and m["mask"] & 0x80
    p.set_motion("A", "LT", 3, ctrl=36)
    m = p.get_motion("A", "LT", 3)
    assert m["ctrl"] == 36 and m["mask"] & 0x09
    # setting ctrl must not clear the tune already there
    assert m["tune"] == -24


def test_zero_tune_is_distinct_from_no_motion():
    """A zero value byte means 'no motion' only when the mask says so."""
    p = blank_pattern()
    assert p.get_motion("A", "LT", 0)["tune"] is None
    p.set_motion("A", "LT", 0, tune=0)
    assert p.get_motion("A", "LT", 0)["tune"] == 0


def test_clear_variation_clears_steps_and_motion():
    p = blank_pattern()
    p.set_steps("A", "BD", "X" * 16)
    p.set_motion("A", "LT", 0, tune=50, ctrl=30)
    p.clear_variation("A")
    assert p.get_steps("A", "BD") == "." * 16
    assert p.get_motion("A", "LT", 0)["mask"] == 0


def test_copy_is_independent():
    p = blank_pattern()
    q = p.copy()
    q.tempo = 90.0
    q.set_steps("A", "BD", "X" * 16)
    assert p.tempo == 126.0
    assert p.get_steps("A", "BD") == "." * 16


# ------------------------------------------------------------------------ kit

def blank_kit() -> Kit:
    raw = bytearray(1312)
    raw[0:16] = b"TESTKIT         "
    return Kit(raw)


def test_kit_rejects_wrong_size():
    with pytest.raises(KitError):
        Kit(bytearray(10))


def test_kit_record_stride():
    assert Kit.record_offset("BD") == 388
    assert Kit.record_offset("SD") == 440
    assert Kit.record_offset("RC") == 388 + 10 * 52


def test_kit_fields_roundtrip():
    k = blank_kit()
    k.set("LT", "tone", 465)
    k.set("LT", "tune", -12)
    k.set("LT", "decay", 150)
    k.set("LT", "pan", -48)
    k.set("LT", "reverb", 140)
    k.set("LT", "delay", 205)
    assert k.get("LT", "tone") == 465
    assert k.get("LT", "tune") == -12
    assert k.get("LT", "decay") == 150
    assert k.get("LT", "pan") == -48
    assert k.get("LT", "reverb") == 140
    assert k.get("LT", "delay") == 205


def test_tune_and_pan_are_offset_binary():
    k = blank_kit()
    k.set("BD", "tune", 0)
    assert k.raw[Kit.record_offset("BD") + 2] == 128
    k.set("BD", "pan", 0)
    assert k.raw[Kit.record_offset("BD") + 6] == 128


def test_level_cannot_be_written():
    k = blank_kit()
    with pytest.raises(KitError) as e:
        k.set("BD", "level", 200)
    assert "fader" in str(e.value)


def test_kit_field_validation():
    k = blank_kit()
    with pytest.raises(KitError):
        k.set("BD", "tune", 200)
    with pytest.raises(KitError):
        k.set("BD", "decay", 300)
    with pytest.raises(KitError):
        k.record_offset("ZZ")


def test_sample_param_detection_and_inheritance():
    donor = blank_kit()
    target = blank_kit()
    assert not donor.has_sample_params("LT")
    # a donor with empty sample bytes must be refused -- this is the bug that
    # made a whole kit inaudible
    with pytest.raises(KitError) as e:
        target.inherit_record("MT", donor, "LT")
    assert "silent" in str(e.value)
    # populate the donor as the device would for a sample tone
    o = donor.record_offset("LT")
    donor.raw[o + 28:o + 42] = bytes([0x18, 0xc8, 0x32, 0, 0, 1, 0, 1, 0,
                                      0xff, 0, 0, 0x20, 0])
    assert donor.has_sample_params("LT")
    target.inherit_record("MT", donor, "LT")
    assert target.has_sample_params("MT")


# --------------------------------------------------------------------- melody

def test_note_parsing():
    assert M.note_to_midi("C3") == 48
    assert M.note_to_midi("A4") == 69
    assert M.note_to_midi("C#3") == 49
    assert M.note_to_midi("Db3") == 49
    assert M.note_to_midi(".") is None
    assert M.note_to_midi("-") is None
    with pytest.raises(M.MelodyError):
        M.note_to_midi("H3")
    with pytest.raises(M.MelodyError):
        M.note_to_midi("C")


def test_note_name_roundtrip():
    for m in range(12, 108):
        assert M.note_to_midi(M.midi_to_note(m)) == m


def test_coarse_encoding_matches_the_measured_panel_values():
    """Panel +12 stored 36, -12 stored 12: exactly semitones + 24."""
    p = blank_pattern()
    M.write(p, "A", "LT", "C4 . C2", "C3", mode="coarse")
    assert p.get_motion("A", "LT", 0)["ctrl"] == 36    # +12 semitones
    assert p.get_motion("A", "LT", 2)["ctrl"] == 12    # -12 semitones


def test_coarse_melody_roundtrip():
    p = blank_pattern()
    tune = "C2 . G2 C3 . D#3 G3 . C4 . G3 D#3 . C3 G2 ."
    warn = M.write(p, "A", "LT", tune, "C3", mode="coarse")
    assert warn == []
    assert M.read(p, "A", "LT", "C3", mode="coarse") == tune


def test_coarse_range_is_four_octaves():
    assert M.coarse_range("C3") == ("C1", "C5")


def test_fine_range_is_under_an_octave():
    lo, hi = M.fine_range("C3")
    span = M.note_to_midi(hi) - M.note_to_midi(lo)
    assert span < 12


def test_out_of_range_notes_warn_and_clamp_not_silently_transpose():
    p = blank_pattern()
    warn = M.write(p, "A", "LT", "C6", "C3", mode="coarse")
    assert len(warn) == 1 and "outside" in warn[0]
    assert p.get_motion("A", "LT", 0)["ctrl"] == 24 + 24   # clamped to +24


def test_strict_mode_raises_instead_of_clamping():
    p = blank_pattern()
    with pytest.raises(M.MelodyError):
        M.write(p, "A", "LT", "C6", "C3", mode="coarse", strict=True)


def test_melody_sounds_only_the_steps_it_writes():
    p = blank_pattern()
    M.write(p, "A", "LT", "C3 . . C3", "C3")
    assert p.get_steps("A", "LT") == "x..x............"


def test_fine_mode_uses_the_measured_scale():
    p = blank_pattern()
    M.write(p, "A", "MT", "D3", "C3", mode="fine")     # +2 semitones
    units = p.get_motion("A", "MT", 0)["tune"]
    assert units == round(2 * M.FINE_UNITS_PER_SEMITONE)


def test_hz_to_note():
    name, cents = M.hz_to_note(440.0)
    assert name == "A4" and abs(cents) < 1
    name, _ = M.hz_to_note(65.4)
    assert name == "C2"
