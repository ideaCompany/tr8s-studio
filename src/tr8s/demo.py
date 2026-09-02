"""
An offline TR-8S, so the studio runs with no hardware attached.

This exists for two reasons. Anyone can try the UI without owning the machine,
and — more usefully during development — the UI can be worked on while the real
port is busy with a long analysis sweep.

It is deliberately a *thin* fake. It reproduces the behaviours that the layers
above have to cope with, and nothing else:

  * a transfer lands in the slot immediately; there is no scratch buffer
  * `level` is overwritten on write, because the physical faders own it
  * an unwritten slot reads back as None

Patterns are generated rather than shipped as captured blobs, so no fixture
files are needed and the demo content is legible in this file.
"""

from __future__ import annotations

import threading

from .kit import SAMPLE_PARAM_OFFSETS
from .kit import TRACKS as KIT_TRACKS
from .kit import Kit
from .melody import write as melody_write
from .pattern import Pattern
from .transport import BLOB_SIZES

FADER_LEVEL = 200
CENTRE = 128            # tune and pan are offset binary: 128 is "no change"
MELODIC = ("LT", "MT")  # the two given a sustained sample tone, for melodies

# Real tone IDs, taken from the measured catalogue rather than invented, so the
# demo kit reads back the way a kit on the machine does. LT and MT get a
# sustained sample tone because those are the tracks the demo plays melodies on.
DEMO_TONES_BY_TRACK = {
    "BD": 191,   # EDM 909 Kick1
    "SD": 213,   # EDM 909 Snare1
    "LT": 451,   # OSC Sine Low   (C2, sustained -- four octaves of Coarse Tune)
    "MT": 455,   # OSC Tri1 Low   (C2, sustained)
    "HT": 35,    # 909 High Tom
    "RS": 36,    # 909 Rim Shot
    "HC": 37,    # 909 Hand Clap
    "CH": 38,    # 909 Closed HH
    "OH": 39,    # 909 Open HH
    "CC": 40,    # 909 Crash Cymbal
    "RC": 41,    # 909 Ride Cymbal
}
MELODIC_ROOT = "C2"     # what 451/455 measured at

# name, tempo, and per-variation step maps. Enough to show arrangement, not a
# transcription of anything.
DEMO_PATTERNS: dict[int, dict] = {
    # 8-01
    114: {
        "name": "DEMOTEK", "tempo": 138.0, "kit": 62,
        "variations": {
            "A": {"BD": "X...X...X...X...", "CH": "..x...x...x...x.",
                  "OH": "....o.......o..."},
            "B": {"BD": "X...X...X...X...", "SD": "....X.......X...",
                  "CH": "..x.x.x...x.x.x.", "RS": "...o...o...o...o"},
            "C": {"BD": "X.......X.......", "SD": "....X.......X...",
                  "CH": "xxxxxxxxxxxxxxxx", "HC": "..o..o..o..o..o."},
        },
        "melody": ("C", "LT", "C2 . D#2 . G2 . A#2 G2 . D#2 . C2 . . . .", MELODIC_ROOT),
    },
    # 8-02
    115: {
        "name": "DEMODNB", "tempo": 174.0, "kit": 63,
        "variations": {
            "A": {"BD": "X.....X.........", "SD": "....X.......X..x",
                  "CH": "..x...x...x...x."},
            "B": {"BD": "X.....X.....X...", "SD": "....X.......X...",
                  "CH": "x.x.x.x.x.x.x.x.", "RS": ".o...o...o...o.."},
        },
    },
    # 8-03
    116: {
        "name": "DEMOLOFI", "tempo": 82.0, "kit": 64,
        "variations": {
            "A": {"BD": "X.......o..X....", "SD": "....x.......x...",
                  "CH": "..o...o...o...o.", "RS": "...........o...."},
        },
        "melody": ("A", "MT", "G2 . . A#2 . C3 . . D3 . C3 . A#2 . . .", MELODIC_ROOT),
    },
}

# a handful of tones so the picker and the melody labels have something real
DEMO_TONES = {
    1: {"name": "808 BD Long", "type": 1, "hz": 52.0, "root": "G#1",
        "decay_ms": 420, "sustained": False, "centroid": 180},
    2: {"name": "909 SD Snap", "type": 1, "hz": 190.0, "root": "F#3",
        "decay_ms": 160, "sustained": False, "centroid": 2400},
    465: {"name": "OSC Saw Low", "type": 2, "hz": 65.4, "root": "C2",
          "decay_ms": None, "sustained": True, "centroid": 1299},
    470: {"name": "Sub Sine", "type": 2, "hz": 55.0, "root": "A1",
          "decay_ms": None, "sustained": True, "centroid": 120},
}


def _build_pattern(spec: dict) -> bytes:
    p = Pattern.from_bytes(bytes(BLOB_SIZES["pattern"]))
    p.name = spec["name"]
    p.tempo = spec["tempo"]
    p.kit = spec["kit"]
    p.shuffle = spec.get("shuffle", 0)      # a blank blob reads as -128
    p.scale = spec.get("scale", "16")
    for v, tracks in spec["variations"].items():
        for inst, steps in tracks.items():
            p.set_steps(v, inst, steps)
    mel = spec.get("melody")
    if mel:
        v, inst, notes, root = mel
        melody_write(p, v, inst, notes, root, mode="coarse")
    return p.to_bytes()


def _build_kit(slot: int) -> bytes:
    k = Kit.from_bytes(bytes(BLOB_SIZES["kit"]))
    k.name = f"DEMO KIT {slot:03d}"
    for inst in KIT_TRACKS:
        k.set(inst, "tone", DEMO_TONES_BY_TRACK[inst])
        k.set(inst, "tune", 0)
        k.set(inst, "pan", 0)
    blob = bytearray(k.to_bytes())
    for inst in KIT_TRACKS:
        off = Kit.record_offset(inst)
        # level is read-only through the model, because the faders own it --
        # but a real kit read back always carries a value, so seed one
        blob[off + 4] = FADER_LEVEL
        if inst in MELODIC:
            # a sample tone on a record with no sample parameters is exactly
            # the bug that made real instruments almost inaudible: seed them,
            # so the demo is self-consistent about which tracks can sing
            for d in SAMPLE_PARAM_OFFSETS:
                blob[off + d] = 64
    return bytes(blob)


class DemoTransport:
    """The Transport surface the layers above actually use, backed by memory."""

    def __init__(self):
        self.path = "demo://tr8s"
        self.device_id = 0x10
        self.on_realtime = None
        self.on_channel = None
        self._lock = threading.RLock()
        self.slots = {
            "pattern": {i: _build_pattern(s) for i, s in DEMO_PATTERNS.items()},
            "kit": {s["kit"]: _build_kit(s["kit"]) for s in DEMO_PATTERNS.values()},
            "tone": {},
            "system": {},
        }
        self.commits: list[tuple[str, int]] = []

    # ------------------------------------------------------------ lifecycle

    def open(self):
        return self

    def close(self):
        pass

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # --------------------------------------------------------------- device

    def firmware(self) -> dict:
        return {"version": "demo", "revision": "0000"}

    def note(self, note, velocity=110, channel=9, length=0.0):
        pass

    def drain(self):
        pass

    def collect(self, idle=0.0, hard_cap=0.0) -> bytes:
        return b""

    # ---------------------------------------------------------------- blobs

    def read_blob(self, kind: str, index: int, timeout: float = 0.0):
        with self._lock:
            return self.slots.get(kind, {}).get(index)

    def send_blob(self, kind: str, slot: int, blob: bytes,
                  settle: float = 0.0, ack_wait: float = 0.0) -> bool:
        if len(blob) != BLOB_SIZES[kind]:
            raise ValueError(f"{kind} blob is {len(blob)} bytes")
        blob = bytearray(blob)
        if kind == "kit":
            for inst in KIT_TRACKS:
                blob[Kit.record_offset(inst) + 4] = FADER_LEVEL
        with self._lock:
            self.slots[kind][slot] = bytes(blob)
        return True

    def commit(self, kind: str, slot: int):
        self.commits.append((kind, slot))


def install() -> DemoTransport:
    """Point the tool layer at an in-memory TR-8S. Returns the transport."""
    from . import tools
    from .device import Device

    t = DemoTransport()
    d = Device(transport=t)
    d.open()
    tools.set_device(d)
    return t


def default_slot() -> int:
    return min(DEMO_PATTERNS)
