"""
A fake Transport backed by captured blobs, so everything above the wire can be
tested with no TR-8S attached.

It deliberately reproduces the device's real behaviours rather than an idealised
version, because those are what the code has to cope with:

  * a transfer writes the slot immediately -- there is no scratch buffer
  * `level` in a kit is overwritten by the "fader" on write
  * reads of an unknown slot return None
"""

from __future__ import annotations

from pathlib import Path

from tr8s.kit import TRACKS as KIT_TRACKS
from tr8s.kit import Kit
from tr8s.transport import BLOB_SIZES

FIXTURES = Path(__file__).parent / "fixtures"


def _blank(kind: str) -> bytes:
    return bytes(BLOB_SIZES[kind])


class FakeTransport:
    """Mimics the Transport surface the layers above actually use."""

    def __init__(self, patterns=None, kits=None, fader_level=200):
        self.path = "fake://tr8s"
        self.device_id = 0x10
        self.on_realtime = None
        self.on_channel = None
        self.fader_level = fader_level
        self.slots = {
            "pattern": dict(patterns or {}),
            "kit": dict(kits or {}),
            "tone": {},
            "system": {},
        }
        self.commits: list[tuple[str, int]] = []
        self.sent: list[tuple[str, int]] = []
        self.opened = False

    # ---------------------------------------------------------- lifecycle

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------- device

    def firmware(self) -> dict:
        return {"version": "2.51", "revision": "0B97"}

    def note(self, note, velocity=110, channel=9, length=0.0):
        pass

    def drain(self):
        pass

    def collect(self, idle=0.0, hard_cap=0.0) -> bytes:
        return b""

    # -------------------------------------------------------------- blobs

    def read_blob(self, kind: str, index: int, timeout: float = 0.0):
        return self.slots.get(kind, {}).get(index)

    def send_blob(self, kind: str, slot: int, blob: bytes,
                  settle: float = 0.0, ack_wait: float = 0.0) -> bool:
        if len(blob) != BLOB_SIZES[kind]:
            raise ValueError(f"{kind} blob is {len(blob)} bytes")
        blob = bytearray(blob)
        if kind == "kit":
            # the device overwrites level with the physical fader position
            for inst in KIT_TRACKS:
                blob[Kit.record_offset(inst) + 4] = self.fader_level
        # a transfer writes the slot straight away -- no scratch buffer
        self.slots[kind][slot] = bytes(blob)
        self.sent.append((kind, slot))
        return True

    def commit(self, kind: str, slot: int):
        self.commits.append((kind, slot))

    # --------------------------------------------------------- the machine

    def select_pattern(self, index: int) -> bool:
        """The temp-address writes that move the machine to a pattern."""
        self.selected = getattr(self, "selected", []) + [index]
        return True


def load_fixture_pattern() -> bytes:
    p = FIXTURES / "pattern.bin"
    return p.read_bytes() if p.exists() else _blank("pattern")


def load_fixture_kit() -> bytes:
    p = FIXTURES / "kit.bin"
    return p.read_bytes() if p.exists() else _blank("kit")


def load_empty_kit() -> bytes:
    """A real blank "----" slot: every sample-parameter byte is zero."""
    p = FIXTURES / "kit_empty.bin"
    return p.read_bytes() if p.exists() else _blank("kit")


def make_device(patterns=None, kits=None):
    """A Device wired to a FakeTransport, pre-loaded with fixtures."""
    from tr8s.device import Device
    pats = patterns if patterns is not None else {0: load_fixture_pattern()}
    kts = kits if kits is not None else {0: load_fixture_kit()}
    t = FakeTransport(patterns=pats, kits=kts)
    d = Device(transport=t)
    d.open()
    return d, t
