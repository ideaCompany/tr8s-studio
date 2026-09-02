"""
Layer 2 — putting a sound file onto the machine.

The TR-8S stores user samples as 16-bit signed little-endian PCM, mono, at
44.1 kHz, in a flat sample memory addressed by byte. Every fact here was read
off one of the machine's own user samples rather than assumed: the frame count
in its pcmTone record divided by its byte span came to 2.00 exactly, and a
slice of the audio decoded as a smooth waveform.

Import is the sequence Roland's own client performs, verbatim:

  1. free_area        -> the top free address in sample memory
  2. send_sample      -> the PCM bytes, to that address
  3. free_tone        -> a free user tone id (624..1023)
  4. send tone        -> the 36-byte record: name, category, type=2 (sample)
  5. send pcm_tone    -> the 64-byte record: where the audio lives
  6. commit tone

Any WAV goes in; the converter below resamples to 44.1 kHz, mixes to mono and
scales to 16 bits with the standard library only, since numpy is not
available here. The odd byte at the end of an odd-length sample is padded,
and a sample that would overflow the longest free run is refused before a
byte is sent.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

RATE = 44100
CATEGORY_IMPORT = 0          # the "IMPORT" category, as on the machine
TONE_TYPE_SAMPLE = 2
MAX_SECONDS = 30.0           # a sanity cap; the machine has ~50 MB in total


class SampleError(ValueError):
    pass


def read_wav(path) -> tuple[int, int, int, bytes]:
    """(channels, rate, sampwidth, frames) via the stdlib `wave` module."""
    with wave.open(str(path), "rb") as w:
        return w.getnchannels(), w.getframerate(), w.getsampwidth(), \
            w.readframes(w.getnframes())


def to_machine_pcm(channels: int, rate: int, width: int, frames: bytes) -> bytes:
    """
    Any PCM WAV -> 16-bit mono 44.1 kHz, the machine's format.

    Pure Python on purpose. It is not fast -- a 10-second file takes a
    second or two -- but it has no dependencies and the results are exact
    for the common cases (16/24-bit, 44.1/48 kHz, mono/stereo).
    """
    if width not in (1, 2, 3, 4):
        raise SampleError(f"unsupported sample width {width * 8} bits")
    n = len(frames) // (width * channels)
    if n == 0:
        raise SampleError("the file has no audio in it")

    # unpack to floats in -1..1, mixing channels as we go
    mono = []
    for i in range(n):
        acc = 0.0
        for c in range(channels):
            off = (i * channels + c) * width
            b = frames[off:off + width]
            if width == 1:
                v = (b[0] - 128) / 128.0
            elif width == 2:
                v = struct.unpack("<h", b)[0] / 32767.0
            elif width == 3:
                v = int.from_bytes(b + (b"\xff" if b[2] & 0x80 else b"\x00"),
                                   "little", signed=True) / 8388608.0
            else:
                v = struct.unpack("<i", b)[0] / 2147483648.0
            acc += v
        mono.append(acc / channels)

    # resample by linear interpolation if the rate differs
    if rate != RATE:
        ratio = rate / RATE
        out_n = int(len(mono) / ratio)
        res = []
        for j in range(out_n):
            x = j * ratio
            i0 = int(x)
            i1 = min(i0 + 1, len(mono) - 1)
            f = x - i0
            res.append(mono[i0] * (1 - f) + mono[i1] * f)
        mono = res

    if len(mono) / RATE > MAX_SECONDS:
        raise SampleError(f"{len(mono) / RATE:.1f}s is longer than the "
                          f"{MAX_SECONDS:.0f}s cap")

    # to int16, clipping rather than wrapping
    out = bytearray()
    for v in mono:
        s = int(round(max(-1.0, min(1.0, v)) * 32767))
        out += struct.pack("<h", s)
    if len(out) % 2:
        out += b"\x00"
    return bytes(out)


def tone_record(name: str, category: int = CATEGORY_IMPORT) -> bytes:
    """The 36-byte tone record: 16-char name, category, type=2, zeros."""
    nm = name.encode("ascii", "replace")[:16].ljust(16, b" ")
    return nm + bytes([category & 0xFF, TONE_TYPE_SAMPLE]) + bytes(18)


# Read off three loaded mono samples (tones 624, 650, 733). +36..+43 is a
# constant; +44 is a u32 that varies per sample with no fixed ratio to its
# length -- a hash or peak value the machine computes. It is copied from a
# known-good record rather than invented; the machine accepts that.
PCM_CONST_28 = bytes.fromhex("02 12 00 00 00 15 00 15")
PCM_CONST_36 = bytes.fromhex("03 65 05 30 02 83 63 24")


def pcm_tone_record(address: int, nbytes: int, frames: int,
                    template: bytes | None = None) -> bytes:
    """
    The 64-byte pcmTone record, as read off the machine's own samples:

      +0  u32 start address    +4  u32 end address
      +8  u32 byte length      +12 u32 zero        (NOT a right channel)
      +16 u32 frames           +20 u32 frames again
      +24 u32 sample rate      +28 8-byte constant
      +36 8-byte constant      +44 u32, per-sample, copied from `template`
      +56 zero

    An earlier version put the left addresses at +8/+12 as a "right
    channel" and 1 at +56. The machine took the sample but the record was
    wrong in every one of those fields.
    """
    end = address + nbytes
    rec = bytearray(64)
    struct.pack_into("<IIII", rec, 0, address, end, nbytes, 0)
    struct.pack_into("<III", rec, 16, frames, frames, RATE)
    rec[28:36] = PCM_CONST_28
    rec[36:44] = PCM_CONST_36
    if template and len(template) >= 48:
        rec[44:48] = template[44:48]
    return bytes(rec)


def import_sample(transport, path, name: str | None = None,
                  category: int = CATEGORY_IMPORT, log=None,
                  reuse_tone: int | None = None) -> dict:
    """
    Put a WAV on the machine as a user tone. Returns the tone id.

    Two modes. With `reuse_tone` the sample is written over that tone's own
    span and its records rebuilt -- replace-in-place. That is the only way
    to recycle sample memory on firmware 2.51: `deleteTone` answers 01 for
    every argument, and the free-space index fragments to sub-sector runs
    after a handful of imports. Without `reuse_tone` a fresh id and the top
    free address are used, and the import is refused before a byte is sent
    if it would not fit the longest free run.
    """
    path = Path(path)
    if not path.is_file():
        raise SampleError(f"no such file: {path}")
    ch, rate, width, frames = read_wav(path)
    pcm = to_machine_pcm(ch, rate, width, frames)
    nframes = len(pcm) // 2
    name = (name or path.stem)[:16]
    template = transport.read_blob("pcm_tone", 624, timeout=6)

    if reuse_tone is not None:
        old = transport.read_blob("pcm_tone", int(reuse_tone), timeout=6)
        if not old:
            raise SampleError(f"tone {reuse_tone} has no record to reuse")
        start, end = struct.unpack_from("<II", old, 0)
        if end - start < len(pcm):
            raise SampleError(
                f"the new sample ({len(pcm)} bytes) is larger than the span "
                f"tone {reuse_tone} holds ({end - start}); a slot can only be "
                f"reused by something that fits in it")
        address, tone_id = start, int(reuse_tone)
    else:
        fa = transport.free_area()
        if len(pcm) > fa["longest_free"]:
            raise SampleError(
                f"{len(pcm) / 1e6:.2f} MB does not fit: the longest free run "
                f"is {fa['longest_free'] / 1e6:.2f} MB ({fa['total_free'] / 1e6:.2f} "
                f"MB free in total, fragmented). Reuse a tone you no longer "
                f"need with reuse_tone.")
        address, tone_id = fa["top_free_address"], None

    if log:
        log(f"{name}: {nframes} frames ({nframes / RATE:.2f}s) -> address {address}")
    if not transport.send_sample(address, pcm):
        raise SampleError("the sample transfer did not complete")
    if tone_id is None:
        tone_id = transport.free_tone()
    if not transport.send_blob("tone", tone_id, tone_record(name, category)):
        raise SampleError("the tone record transfer did not complete")
    if not transport.send_blob("pcm_tone", tone_id,
                               pcm_tone_record(address, len(pcm), nframes,
                                               template)):
        raise SampleError("the pcm-tone record transfer did not complete")
    transport.commit("tone", tone_id)
    return {"tone": tone_id, "name": name, "frames": nframes,
            "seconds": round(nframes / RATE, 3), "bytes": len(pcm),
            "address": address, "category": category,
            "reused": reuse_tone is not None}
