"""
Layer 2 — the Pattern model. Parses and builds the 24504-byte blob.

Layout is documented in docs/PROTOCOL.md. In brief:

    0..15    name             16..17  tempo (tenths of a BPM)
    18       kit (1-based)    19      scale        32  shuffle
    144 + blk*2436            variation block, blk 0..9
      +4 + track*64 + step*4  4 bytes per step
        instrument tracks 0..10 : byte 0 = velocity
        motion lanes 12..22     : 0 = tune, 2 = ctrl, 3 = presence mask
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

TRACKS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC"]
VARIATIONS = "ABCDEFGH"

SIZE = 24504
HEADER = 144
BLOCK = 2436
NBLOCKS = 10
TRACK_BASE = 4
TRACK_STRIDE = 64
STEP_STRIDE = 4
STEPS = 16

OFF_NAME = slice(0, 16)
OFF_TEMPO = 16
OFF_KIT = 18
OFF_SCALE = 19
OFF_SHUFFLE = 32

SCALES = {"8T": 0, "16T": 1, "16": 2, "32": 3}
SCALE_NAMES = {v: k for k, v in SCALES.items()}

VELOCITY = {"X": 112, "x": 100, "o": 55}
MOTION_TUNE_LANE_BASE = 12
MASK_TUNE = 0x80
MASK_CTRL = 0x09


def _char_for(v: int) -> str:
    if v >= 112:
        return "X"
    if v >= 90:
        return "x"
    if v:
        return "o"
    return "."


class PatternError(ValueError):
    pass


@dataclass
class Pattern:
    """A mutable TR-8S pattern. `raw` is always a valid 24504-byte blob."""

    raw: bytearray = field(repr=False)

    def __post_init__(self):
        if len(self.raw) != SIZE:
            raise PatternError(f"pattern blob is {len(self.raw)} bytes, expected {SIZE}")
        self.raw = bytearray(self.raw)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "Pattern":
        return cls(bytearray(blob))

    def to_bytes(self) -> bytes:
        return bytes(self.raw)

    def copy(self) -> "Pattern":
        return Pattern(bytearray(self.raw))

    # ------------------------------------------------------------- header

    @property
    def name(self) -> str:
        return bytes(self.raw[OFF_NAME]).decode("ascii", "replace").rstrip()

    @name.setter
    def name(self, value: str):
        self.raw[OFF_NAME] = value[:16].ljust(16).encode("ascii", "replace")

    @property
    def tempo(self) -> float:
        return struct.unpack_from("<H", self.raw, OFF_TEMPO)[0] / 10.0

    @tempo.setter
    def tempo(self, bpm: float):
        if not 40.0 <= bpm <= 300.0:
            raise PatternError(f"tempo {bpm} out of range 40..300")
        struct.pack_into("<H", self.raw, OFF_TEMPO, int(round(bpm * 10)))

    @property
    def kit(self) -> int:
        """0-based kit index (the panel shows this + 1)."""
        return self.raw[OFF_KIT] - 1

    @kit.setter
    def kit(self, index: int):
        if not 0 <= index <= 127:
            raise PatternError(f"kit index {index} out of range 0..127")
        self.raw[OFF_KIT] = index + 1

    @property
    def scale(self) -> str:
        return SCALE_NAMES.get(self.raw[OFF_SCALE], str(self.raw[OFF_SCALE]))

    @scale.setter
    def scale(self, value: str):
        if value not in SCALES:
            raise PatternError(f"scale must be one of {sorted(SCALES)}")
        self.raw[OFF_SCALE] = SCALES[value]

    @property
    def shuffle(self) -> int:
        return self.raw[OFF_SHUFFLE] - 128

    @shuffle.setter
    def shuffle(self, amount: int):
        if not -128 <= amount <= 127:
            raise PatternError("shuffle must be -128..127")
        self.raw[OFF_SHUFFLE] = (amount + 128) & 0xFF

    # ------------------------------------------------------------ offsets

    @staticmethod
    def _blk(variation) -> int:
        if isinstance(variation, int):
            blk = variation
        else:
            v = str(variation).upper()
            if v not in VARIATIONS:
                raise PatternError(f"variation must be one of {VARIATIONS}")
            blk = VARIATIONS.index(v)
        if not 0 <= blk < NBLOCKS:
            raise PatternError(f"variation block {blk} out of range")
        return blk

    @classmethod
    def _step_offset(cls, blk: int, track: int, step: int) -> int:
        return (HEADER + blk * BLOCK + TRACK_BASE
                + track * TRACK_STRIDE + step * STEP_STRIDE)

    @classmethod
    def _inst_offset(cls, blk: int, inst: str, step: int) -> int:
        if inst not in TRACKS:
            raise PatternError(f"unknown instrument {inst!r}; expected one of {TRACKS}")
        return cls._step_offset(blk, TRACKS.index(inst), step)

    @classmethod
    def _motion_offset(cls, blk: int, inst: str, step: int) -> int:
        if inst not in TRACKS:
            raise PatternError(f"unknown instrument {inst!r}")
        return cls._step_offset(blk, MOTION_TUNE_LANE_BASE + TRACKS.index(inst), step)

    # -------------------------------------------------------------- steps

    def get_steps(self, variation, inst: str) -> str:
        blk = self._blk(variation)
        return "".join(_char_for(self.raw[self._inst_offset(blk, inst, s)])
                       for s in range(STEPS))

    def set_steps(self, variation, inst: str, pattern: str):
        """`pattern` is up to 16 characters of X (accent), x, o (ghost) or . """
        blk = self._blk(variation)
        if len(pattern) > STEPS:
            raise PatternError(f"{len(pattern)} steps; a variation holds {STEPS}")
        bad = set(pattern) - set("Xxo.")
        if bad:
            raise PatternError(f"illegal step characters {sorted(bad)}; use X x o .")
        for s in range(STEPS):
            ch = pattern[s] if s < len(pattern) else "."
            self.raw[self._inst_offset(blk, inst, s)] = VELOCITY.get(ch, 0)

    def clear_variation(self, variation):
        blk = self._blk(variation)
        for track in range(len(TRACKS)):
            for s in range(STEPS):
                o = self._step_offset(blk, track, s)
                self.raw[o] = 0
        for inst in TRACKS:
            for s in range(STEPS):
                o = self._motion_offset(blk, inst, s)
                self.raw[o] = self.raw[o + 2] = self.raw[o + 3] = 0

    def variation_summary(self, variation) -> dict:
        blk = self._blk(variation)
        out = {}
        for inst in TRACKS:
            steps = self.get_steps(blk, inst)
            if steps.strip("."):
                out[inst] = steps
        return out

    # ------------------------------------------------------------- motion

    def set_motion(self, variation, inst: str, step: int,
                   tune: int | None = None, ctrl: int | None = None):
        """
        Write per-step motion. `tune` is -128..127 (fine), `ctrl` is the raw
        CTRL byte. The presence mask must be set or the step is ignored.
        """
        blk = self._blk(variation)
        o = self._motion_offset(blk, inst, step)
        mask = self.raw[o + 3]
        if tune is not None:
            if not -128 <= tune <= 127:
                raise PatternError("tune must be -128..127")
            self.raw[o] = (tune + 128) & 0xFF
            mask |= MASK_TUNE
        if ctrl is not None:
            self.raw[o + 2] = ctrl & 0xFF
            mask |= MASK_CTRL
        self.raw[o + 3] = mask

    def get_motion(self, variation, inst: str, step: int) -> dict:
        blk = self._blk(variation)
        o = self._motion_offset(blk, inst, step)
        mask = self.raw[o + 3]
        return {
            "tune": self.raw[o] - 128 if mask & MASK_TUNE else None,
            "ctrl": self.raw[o + 2] if mask & MASK_CTRL else None,
            "mask": mask,
        }

    def clear_motion(self, variation, inst: str, step: int | None = None):
        """Clear motion on one step, or on every step when `step` is None."""
        blk = self._blk(variation)
        steps = range(STEPS) if step is None else [step]
        for s in steps:
            if not 0 <= s < STEPS:
                raise PatternError(f"step {s} out of range 0..{STEPS - 1}")
            o = self._motion_offset(blk, inst, s)
            self.raw[o] = self.raw[o + 2] = self.raw[o + 3] = 0

    # --------------------------------------------------------------- info

    def describe(self) -> dict:
        return {
            "name": self.name,
            "tempo": self.tempo,
            "kit": self.kit,
            "kit_panel": self.kit + 1,
            "scale": self.scale,
            "shuffle": self.shuffle,
            "variations": {
                v: self.variation_summary(v)
                for v in VARIATIONS
                if self.variation_summary(v)
            },
        }
