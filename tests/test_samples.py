"""
Sample conversion and the import record layouts. No machine: the converter
is checked on synthetic WAVs, and the records against the bytes read off a
real user sample (documented in samples.py).
"""

import struct
import wave

import pytest

from tr8s.samples import (RATE, SampleError, pcm_tone_record, to_machine_pcm,
                          tone_record)


def wav_bytes(path, channels=1, rate=44100, width=2, seconds=0.1, amp=0.5):
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setframerate(rate); w.setsampwidth(width)
        frames = bytearray()
        for i in range(n):
            v = amp * (1 if (i // 20) % 2 == 0 else -1)      # a square wave
            for c in range(channels):
                if width == 2:
                    frames += struct.pack("<h", int(v * 32767))
                elif width == 1:
                    frames += bytes([int(v * 127) + 128])
                elif width == 3:
                    frames += int(v * 8388607).to_bytes(3, "little", signed=True)
        w.writeframes(bytes(frames))
    return n


def test_16bit_mono_44k_passes_through_unchanged(tmp_path):
    p = tmp_path / "a.wav"; n = wav_bytes(p)
    with wave.open(str(p)) as w:
        raw = w.readframes(w.getnframes())
    out = to_machine_pcm(1, 44100, 2, raw)
    assert out == raw and len(out) == n * 2


def test_stereo_is_mixed_to_mono(tmp_path):
    p = tmp_path / "s.wav"; n = wav_bytes(p, channels=2)
    with wave.open(str(p)) as w:
        raw = w.readframes(w.getnframes())
    out = to_machine_pcm(2, 44100, 2, raw)
    assert len(out) == n * 2, "one frame per stereo pair"


def test_48k_is_resampled_to_44k(tmp_path):
    p = tmp_path / "r.wav"; n = wav_bytes(p, rate=48000)
    with wave.open(str(p)) as w:
        raw = w.readframes(w.getnframes())
    out = to_machine_pcm(1, 48000, 2, raw)
    assert abs(len(out) // 2 - n * 44100 / 48000) <= 1


def test_8_and_24_bit_scale_correctly(tmp_path):
    for width in (1, 3):
        p = tmp_path / f"w{width}.wav"; wav_bytes(p, width=width, amp=0.5)
        with wave.open(str(p)) as w:
            raw = w.readframes(w.getnframes())
        out = to_machine_pcm(1, 44100, width, raw)
        peak = max(abs(s) for s in struct.unpack("<" + "h" * (len(out) // 2), out))
        assert 0.4 * 32767 < peak < 0.6 * 32767, (width, peak)


def test_output_is_always_16bit_frames():
    out = to_machine_pcm(1, 44100, 2, struct.pack("<3h", 1, 2, 3))
    assert len(out) % 2 == 0


def test_empty_audio_is_refused():
    with pytest.raises(SampleError):
        to_machine_pcm(1, 44100, 2, b"")


def test_too_long_is_refused():
    with pytest.raises(SampleError, match="cap"):
        to_machine_pcm(1, 44100, 2, b"\x00\x00" * (RATE * 31))


def test_clipping_clips_rather_than_wrapping():
    """Both channels at full scale, same sign: the mono sum must not wrap."""
    hot = struct.pack("<2h", 32767, 32767)          # one stereo frame, L+R hot
    cold = struct.pack("<2h", -32768, -32768)
    out = to_machine_pcm(2, 44100, 2, hot + cold)
    vals = struct.unpack("<2h", out)
    assert vals[0] == 32767 and vals[1] == -32767


# ---------------------------------------------------------------- records

def test_tone_record_is_36_bytes_with_the_observed_layout():
    r = tone_record("09_MHT_Bass_hit_", category=0)
    assert len(r) == 36
    assert r[:16] == b"09_MHT_Bass_hit_"
    assert r[16] == 0 and r[17] == 2                  # category, type=sample
    assert r[18:] == bytes(18)


def test_tone_record_pads_and_truncates_the_name():
    assert tone_record("kick")[:16] == b"kick            "
    assert tone_record("a" * 40)[:16] == b"a" * 16


def test_pcm_tone_record_matches_the_bytes_read_off_the_machine():
    """
    Tone 624 on the real machine: start 13631488, 87206 bytes, 43602 frames.
    Its record: 00 00 d0 00 | a6 54 d1 00 | a6 54 01 00 | 00 00 00 00 ...
    i.e. start, end, BYTE LENGTH, zero -- not a right-channel pair.
    """
    tmpl = bytes(44) + bytes.fromhex("2c 6d 00 00") + bytes(16)
    r = pcm_tone_record(13631488, 87206, 43602, template=tmpl)
    assert len(r) == 64
    assert r[:16].hex(" ") == "00 00 d0 00 a6 54 d1 00 a6 54 01 00 00 00 00 00"
    assert struct.unpack_from("<III", r, 16) == (43602, 43602, 44100)
    assert r[28:36] == bytes.fromhex("02 12 00 00 00 15 00 15")
    assert r[36:44] == bytes.fromhex("03 65 05 30 02 83 63 24")
    assert r[44:48] == bytes.fromhex("2c 6d 00 00"), "the per-sample word is copied"
    assert r[56] == 0


def test_pcm_tone_record_without_a_template_leaves_the_word_zero():
    r = pcm_tone_record(100, 200, 100)
    assert r[44:48] == bytes(4)
