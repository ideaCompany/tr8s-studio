"""
Layer 2 — a tagged log of every change to the kit and patterns this session.

Who changed what, and how. Three sources:

  **user**   — a hand on the machine: a knob turned, a fader moved, a step
               entered on the panel. Knobs and faders are read from MIDI
               Control Change; steps from reading the pattern back and diffing,
               since the panel transmits nothing when a step is pressed.
  **ai**     — a tool the chat assistant called.
  **studio** — a tool the browser UI called.

It exists for two reasons. During development it answers "what just happened
and who did it", which is otherwise guesswork across MIDI, SysEx and three
UIs. And it is the memory an AI collaborator needs: to reason about a track it
has to know that the user shortened the snare and added a hat two bars ago,
not just see the final state.

Entries persist to a session file so they survive a studio restart mid-session.
Verbose by default; toggle with `enabled`.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field

SOURCES = ("user", "ai", "studio", "system")


@dataclass
class Change:
    source: str                 # user | ai | studio | system
    action: str                 # e.g. "step added", "knob", "tone", "fader"
    instrument: str | None = None
    detail: str = ""            # human-readable, e.g. "DECAY -> +11"
    slot: int | None = None
    at: float = field(default_factory=lambda: 0.0)

    def line(self) -> str:
        who = self.source.upper()
        where = f" {self.instrument}" if self.instrument else ""
        what = f": {self.detail}" if self.detail else ""
        return f"[{who}] {self.action}{where}{what}"


class ChangeLog:
    def __init__(self, limit: int = 2000):
        self._lock = threading.RLock()
        self._items: list[Change] = []
        self.limit = limit
        self.enabled = True
        self.started = _now()
        self._path = None
        # coalesce a rapid run of the same control into one entry, so turning a
        # knob does not write forty lines -- only its latest value
        self._coalesce_window = 1.5
        self._dirty = False

    def bind(self, path):
        """Point at a session file and load anything already there."""
        from pathlib import Path
        self._path = Path(path)
        if self._path.is_file():
            try:
                with self._path.open() as f:
                    for ln in f:
                        d = json.loads(ln)
                        self._items.append(Change(**d))
                self._items = self._items[-self.limit:]
            except (ValueError, OSError):
                pass

    def add(self, source: str, action: str, instrument: str | None = None,
            detail: str = "", slot: int | None = None,
            coalesce_key: str | None = None) -> Change | None:
        """
        Record a change. Returns the entry, or None when disabled.

        `coalesce_key` folds a rapid burst (a knob sweep) into one line: if the
        previous entry shares the key and arrived within the window, it is
        updated in place rather than appended.
        """
        if not self.enabled:
            return None
        now = _now()
        c = Change(source=source, action=action, instrument=instrument,
                   detail=detail, slot=slot, at=round(now - self.started, 3))
        with self._lock:
            # The entry to fold into: the most recent one with this key within
            # the window -- not only the very last entry. Two controls
            # arriving interleaved (the machine streams motion for CTRL and
            # LEVEL together while playing) defeated a last-entry-only check
            # and flooded the log with a line every 200 ms.
            last = None
            if coalesce_key is not None:
                for prev in reversed(self._items[-8:]):
                    if (getattr(prev, "_key", None) == coalesce_key
                            and now - getattr(prev, "_abs", 0) < self._coalesce_window):
                        last = prev
                        break
            if last is not None:
                if detail == getattr(last, "_last_detail", None):
                    last._abs = now          # the same value again: nothing new
                    return last
                last._last_detail = detail
                if True:
                    # a knob sweep: update in memory, mark the file stale, but
                    # do NOT rewrite per CC. The stale value is flushed when the
                    # next distinct entry is appended, or on read. Show the net
                    # gesture -- where it started, where it settled, how long --
                    # rather than only the final value, so one line tells the
                    # whole move instead of a hundred.
                    dur = now - getattr(last, "_start_abs", now)
                    first = getattr(last, "_first_detail", last.detail)
                    fa, fb = first.split(" ", 1), detail.split(" ", 1)
                    if len(fa) == 2 and len(fb) == 2 and fa[0] == fb[0]:
                        shown = f"{fa[0]} {fa[1]} \u2192 {fb[1]}"
                    elif first != detail:
                        shown = f"{first} \u2192 {detail}"
                    else:
                        shown = detail
                    last.detail = (f"{shown} ({dur:.1f}s)" if dur >= 0.2
                                   else shown)
                    last.at = c.at
                    last._abs = now
                    self._dirty = True
                    return last
            c._key = coalesce_key
            c._abs = now
            if coalesce_key is not None:
                c._first_detail = detail
                c._last_detail = detail
                c._start_abs = now
            self._items.append(c)
            del self._items[:-self.limit]
            if self._dirty:
                self._rewrite(); self._dirty = False   # settle the last sweep
            else:
                self._append(c)
        return c

    def recent(self, limit: int = 100, source: str | None = None) -> list[dict]:
        with self._lock:
            if self._dirty:
                self._rewrite(); self._dirty = False
            items = self._items
            if source:
                items = [c for c in items if c.source == source]
            return [_public(c) for c in items[-limit:]][::-1]

    def as_text(self, limit: int = 200) -> str:
        with self._lock:
            rows = [f"{c.at:9.2f}  {c.line()}" for c in self._items[-limit:]]
        return "\n".join(["# TR-8S change log (this session)", "#"] + rows)

    def clear(self):
        with self._lock:
            self._items.clear()
            self.started = _now()
            if self._path:
                try:
                    self._path.write_text("")
                except OSError:
                    pass

    def __len__(self):
        with self._lock:
            return len(self._items)

    # ------------------------------------------------------------- disk

    def _append(self, c: Change):
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(json.dumps(_public(c)) + "\n")
        except OSError:
            pass

    def _rewrite(self):
        if not self._path:
            return
        try:
            with self._path.open("w") as f:
                for c in self._items:
                    f.write(json.dumps(_public(c)) + "\n")
        except OSError:
            pass


def _now() -> float:
    return time.monotonic()


def _public(c: Change) -> dict:
    return {k: v for k, v in asdict(c).items() if not k.startswith("_")}


CHANGELOG = ChangeLog()
