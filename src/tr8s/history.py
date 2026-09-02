"""
Layer 2 — undo.

Every write lands in the slot immediately; there is no scratch buffer and the
machine offers nothing to step back to. That makes experimenting expensive,
which is the opposite of what this is for.

So: before a mutating tool runs, the affected blob is kept. A pattern is 24 KB
and a kit 1.3 KB, so a few dozen steps of history cost about a megabyte —
nothing, against the cost of losing a pattern you liked.

The snapshot is taken from the device's own read cache when possible. A read is
about 0.6 s over SysEx, and paying that before every step edit would make the
UI feel broken; the cache holds whatever was last read or written, which for an
edit in progress is exactly the right bytes.

What this cannot do: undo something the device changed by itself, or anything
done from the panel. It only knows about writes that went through these tools.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

LIMIT = 64
KINDS = ("pattern", "kit")


@dataclass
class Snapshot:
    kind: str
    slot: int
    blob: bytes = field(repr=False)
    label: str
    at: float

    def describe(self) -> dict:
        from .device import slot_to_panel
        return {"kind": self.kind, "slot": self.slot,
                "panel": slot_to_panel(self.slot) if self.kind == "pattern"
                         else self.slot + 1,
                "label": self.label,
                "seconds_ago": round(time.time() - self.at, 1)}


class History:
    def __init__(self, limit: int = LIMIT):
        self._undo: deque[Snapshot] = deque(maxlen=limit)
        self._redo: list[Snapshot] = []
        self._lock = threading.RLock()
        self.enabled = True

    # ------------------------------------------------------------- capture

    def capture(self, dev, kind: str, slot: int, label: str) -> bool:
        """
        Record the current contents of a slot. Returns False when there was
        nothing to record — an empty slot, or a device that would not read.

        A failure here must never block the edit: losing undo is annoying,
        refusing to write is worse.
        """
        if not self.enabled or kind not in KINDS:
            return False
        try:
            blob = dev.snapshot(kind, slot)
        except Exception:
            return False
        if not blob:
            return False
        with self._lock:
            self._undo.append(Snapshot(kind, slot, bytes(blob), label,
                                       time.time()))
            self._redo.clear()      # a new edit forks the timeline
        return True

    # -------------------------------------------------------------- replay

    def undo(self, dev) -> dict:
        with self._lock:
            if not self._undo:
                raise LookupError("nothing to undo")
            snap = self._undo.pop()
        current = None
        try:
            current = dev.snapshot(snap.kind, snap.slot)
        except Exception:
            pass
        self._restore(dev, snap)
        if current:
            with self._lock:
                self._redo.append(Snapshot(snap.kind, snap.slot, bytes(current),
                                           f"redo {snap.label}", time.time()))
        return {"undone": snap.label, **snap.describe()}

    def redo(self, dev) -> dict:
        with self._lock:
            if not self._redo:
                raise LookupError("nothing to redo")
            snap = self._redo.pop()
        current = None
        try:
            current = dev.snapshot(snap.kind, snap.slot)
        except Exception:
            pass
        self._restore(dev, snap)
        if current:
            with self._lock:
                self._undo.append(Snapshot(snap.kind, snap.slot, bytes(current),
                                           snap.label, time.time()))
        return {"redone": snap.label, **snap.describe()}

    @staticmethod
    def _restore(dev, snap: Snapshot):
        from .device import DeviceError
        if not dev.transport.send_blob(snap.kind, snap.slot, snap.blob):
            raise DeviceError(f"could not restore {snap.kind} {snap.slot}")
        dev.transport.commit(snap.kind, snap.slot)
        dev.remember(snap.kind, snap.slot, snap.blob)

    # ---------------------------------------------------------------- info

    def entries(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [s.describe() for s in list(self._undo)[-limit:]][::-1]

    def redo_entries(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [s.describe() for s in self._redo[-limit:]][::-1]

    def clear(self):
        with self._lock:
            self._undo.clear()
            self._redo.clear()

    def __len__(self):
        with self._lock:
            return len(self._undo)


HISTORY = History()
