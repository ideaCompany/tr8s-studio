"""
Layer 2 — the Kit model. Parses and builds the 1312-byte blob.

    0..15         name
    388 + i*52    instrument record, i = 0..10 in panel order
      +0..1 tone   +2 tune   +3 decay   +4 level (READ-ONLY)
      +6 pan       +7 reverb +8 delay   +11 lfo
      +28..+41     envelope/gain fields a SAMPLE tone needs (gain at +37)

Two hard-won rules, both in docs/PROTOCOL.md:

  * `level` cannot be written -- the device overwrites it with the physical
    fader position on every save.
  * Writing a SAMPLE tone id is not enough. A sample needs the envelope/gain
    fields in +28..+41, and a blank "----" slot has them all at zero, which
    makes the tone play almost inaudibly. Inherit a working record first.
    (These are not *exclusively* sample fields: measured across 839 records on
    this device, ACB instruments populate them ~43% of the time and samples
    ~95%. See SAMPLE_PARAM_OFFSETS.)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

TRACKS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC"]

SIZE = 1312
REC_BASE = 388
REC_STRIDE = 52
# Bytes carrying a sample's envelope and gain. Measured across 669 ACB and 170
# sample records from this device: none of these is exclusively a sample field
# (ACB records populate them ~43% of the time) but a SAMPLE record has them set
# ~95% of the time, and a blank "----" slot has them all at zero. So this is a
# majority vote, not a clean predicate -- it exists to catch the blank-record
# case that makes an assigned sample tone near-silent.
SAMPLE_PARAM_OFFSETS = (29, 30, 33, 35, 37, 40)
SAMPLE_PARAMS = slice(28, 42)          # copied wholesale when inheriting

FIELDS = {
    "tone": (0, 2, False),
    "tune": (2, 1, True),
    "decay": (3, 1, False),
    "level": (4, 1, False),
    "pan": (6, 1, True),
    "reverb": (7, 1, False),
    "delay": (8, 1, False),
    "lfo": (11, 1, False),
}
READONLY = {"level"}

# Per-instrument fader colour: eleven consecutive bytes in the kit header, one
# per instrument in TRACKS order, values 0..11.
#
# **[I]** Identified statistically, not by watching the machine. Across 128
# factory kits these eleven bytes are the only run of exactly eleven with a
# small shared palette, they vary per kit, and an *empty* kit carries the
# default [0,1,3,3,3,1,1,2,2,2,2] -- which groups by category (kick, snare,
# toms, rimshot/clap, hats and cymbals), the shape a factory colour scheme
# has. What each index looks like has NOT been confirmed against the panel;
# see COLOUR_NAMES.
COLOR_BASE = 42
COLOR_COUNT = 12

# **[U]** The palette itself is a guess, fitted to the default scheme above and
# to product photography. Treat the names as labels for indices, not as facts
# about the LEDs.
COLOUR_NAMES = ["red", "orange", "yellow", "green", "teal", "cyan",
                "blue", "indigo", "violet", "magenta", "pink", "white"]


class KitError(ValueError):
    pass


@dataclass
class Kit:
    raw: bytearray = field(repr=False)

    def __post_init__(self):
        if len(self.raw) != SIZE:
            raise KitError(f"kit blob is {len(self.raw)} bytes, expected {SIZE}")
        self.raw = bytearray(self.raw)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "Kit":
        return cls(bytearray(blob))

    def to_bytes(self) -> bytes:
        return bytes(self.raw)

    def copy(self) -> "Kit":
        return Kit(bytearray(self.raw))

    @staticmethod
    def record_offset(inst: str) -> int:
        if inst not in TRACKS:
            raise KitError(f"unknown instrument {inst!r}; expected one of {TRACKS}")
        return REC_BASE + TRACKS.index(inst) * REC_STRIDE

    @property
    def name(self) -> str:
        return bytes(self.raw[0:16]).decode("ascii", "replace").rstrip()

    @name.setter
    def name(self, value: str):
        self.raw[0:16] = value[:16].ljust(16).encode("ascii", "replace")

    # -------------------------------------------------------------- fields

    def get(self, inst: str, field_name: str) -> int:
        off, size, signed = FIELDS[field_name]
        o = self.record_offset(inst) + off
        if size == 2:
            return struct.unpack_from("<H", self.raw, o)[0]
        v = self.raw[o]
        return v - 128 if signed else v

    def set(self, inst: str, field_name: str, value: int):
        if field_name in READONLY:
            raise KitError(
                f"'{field_name}' is device-controlled (the physical fader) and "
                f"cannot be written from software"
            )
        off, size, signed = FIELDS[field_name]
        o = self.record_offset(inst) + off
        if size == 2:
            struct.pack_into("<H", self.raw, o, value & 0xFFFF)
            return
        if signed:
            if not -128 <= value <= 127:
                raise KitError(f"{field_name} must be -128..127")
            value += 128
        elif not 0 <= value <= 255:
            raise KitError(f"{field_name} must be 0..255")
        self.raw[o] = value & 0xFF

    def color(self, inst: str) -> int:
        """The instrument's fader colour index, 0..11. See COLOR_BASE."""
        return self.raw[COLOR_BASE + TRACKS.index(inst)]

    def set_color(self, inst: str, index: int):
        if not 0 <= int(index) < COLOR_COUNT:
            raise KitError(f"colour must be 0..{COLOR_COUNT - 1}")
        self.raw[COLOR_BASE + TRACKS.index(inst)] = int(index)

    def colors(self) -> dict:
        return {i: self.color(i) for i in TRACKS}

    def has_sample_params(self, inst: str, minimum: int = 4) -> bool:
        """
        Whether this record looks equipped to host a SAMPLE tone.

        Heuristic by necessity -- see SAMPLE_PARAM_OFFSETS. A blank slot scores
        zero, a real sample instrument scores six.
        """
        o = self.record_offset(inst)
        return sum(1 for d in SAMPLE_PARAM_OFFSETS if self.raw[o + d]) >= minimum

    def inherit_record(self, inst: str, donor: "Kit", donor_inst: str):
        """
        Copy a whole 52-byte instrument record from a donor.

        Use this before assigning a SAMPLE tone to an instrument whose record
        currently holds ACB defaults, or the tone will be near-silent.
        """
        if not donor.has_sample_params(donor_inst):
            raise KitError(
                f"donor {donor.name!r}/{donor_inst} has empty sample parameters; "
                f"copying it would produce a silent tone"
            )
        d = donor.record_offset(donor_inst)
        o = self.record_offset(inst)
        self.raw[o:o + REC_STRIDE] = donor.raw[d:d + REC_STRIDE]

    def describe(self) -> dict:
        out = {"name": self.name, "instruments": {}}
        for inst in TRACKS:
            out["instruments"][inst] = {
                f: self.get(inst, f) for f in FIELDS
            }
            out["instruments"][inst]["sample_params"] = self.has_sample_params(inst)
            ci = self.color(inst)
            out["instruments"][inst]["color"] = ci
            out["instruments"][inst]["color_name"] = (
                COLOUR_NAMES[ci] if ci < len(COLOUR_NAMES) else str(ci))
        return out
