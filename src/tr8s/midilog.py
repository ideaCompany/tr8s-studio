"""
A readable log of what the machine sends.

Written because "is any MIDI arriving, and what?" was the question behind
several hours of wrong guesses. Answering it took a throwaway capture script
each time; it should be visible in the app.

Each entry is decoded rather than raw hex, and says what the studio does with
it -- a message that arrives but is not used is exactly as interesting as one
that never arrives.
"""

from __future__ import annotations

import threading
import time

# What the studio actually does with each kind of message. The point of saying
# so is that "arriving but ignored" and "never arrives" look identical in a
# raw dump, and they mean completely different things.
USES = {
    "clock": "keeps the playhead and the tempo readout",
    "start": "not used — the machine does not send one it did not receive",
    "stop": "not used; playing is inferred from notes",
    "continue": "not used",
    "note on": "identifies the pattern and variation being played",
    "note off": "ignored",
    "program": "follows the pattern selected on the panel "
               "(needs UTILITY MIDI Tx Prog Chg = ON)",
    "control": "moves the knob or fader on screen; CC 2 is the beat counter "
               "(needs UTILITY MIDI Tx EditData = ON)",
    "pitchbend": "ignored",
    "aftertouch": "ignored",
    "sysex": "replies to what the studio asked for",
    "beat": "the bar position, sent every beat while playing — pins the phase",
}

INST_LABEL = {36: "BD", 38: "SD", 43: "LT", 47: "MT", 50: "HT", 37: "RS",
              39: "HC", 42: "CH", 46: "OH", 49: "CC", 51: "RC"}


class MidiLog:
    """A rolling window of decoded messages, newest last."""

    def __init__(self, limit: int = 300):
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._counts: dict[str, int] = {}
        self.limit = limit
        self.started = time.monotonic()
        self._clock = 0
        # clock is 24 messages a beat and would drown everything else
        self.show_clock = False

    def feed(self, data: bytes, source: str = "in"):
        # Clock arrives 24 times a beat, on the MIDI reader thread. Decoding it
        # into dicts and taking a lock for each one made the UI lag; count it
        # and move on unless someone has asked to see it.
        b = bytes(data)
        if not self.show_clock and all(x == 0xF8 for x in b):
            self._clock += len(b)
            return
        for msg in decode(b):
            self._add(msg, source)

    def _add(self, msg: dict, source: str):
        with self._lock:
            self._counts[msg["kind"]] = self._counts.get(msg["kind"], 0) + 1
            if msg["kind"] == "clock" and not self.show_clock:
                return
            # the beat counter arrives every beat while playing and would push
            # a real knob move out of the window within seconds. Count it
            # separately; show it only with the clock.
            if msg["kind"] == "control" and msg["hex"].startswith("b9 02 "):
                self._counts["beat"] = self._counts.get("beat", 0) + 1
                self._counts["control"] -= 1
                if not self.show_clock:
                    return
            msg["at"] = round(time.monotonic() - self.started, 3)
            msg["source"] = source
            self._items.append(msg)
            del self._items[:-self.limit]

    def entries(self, limit: int = 120) -> list[dict]:
        with self._lock:
            return self._items[-limit:]

    def summary(self) -> list[dict]:
        with self._lock:
            counts = dict(self._counts)
            if self._clock:
                counts["clock"] = counts.get("clock", 0) + self._clock
        return [{"kind": k, "count": n, "used_for": USES.get(k, "")}
                for k, n in sorted(counts.items(), key=lambda x: -x[1])]

    def clear(self):
        with self._lock:
            self._items.clear()
            self._counts.clear()
            self._clock = 0
            self.started = time.monotonic()

    def as_text(self, limit: int = 120) -> str:
        """Plain text, for pasting somewhere."""
        lines = [f"{e['at']:9.3f}  {e['kind']:<11} {e['detail']:<28} {e['hex']}"
                 for e in self.entries(limit)]
        head = ["# TR-8S MIDI received", "#", "# counts:"]
        head += [f"#   {s['kind']:<11} x{s['count']:<6} {s['used_for']}"
                 for s in self.summary()]
        head.append("#")
        return "\n".join(head + lines)


def decode(data: bytes) -> list[dict]:
    """Split a chunk into decoded messages. Unknown bytes are skipped."""
    out: list[dict] = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0xF0:                       # sysex, to its terminator
            j = i
            while j < n and data[j] != 0xF7:
                j += 1
            out.append(_m("sysex", f"{j - i + 1} bytes", data[i:j + 1][:8]))
            i = j + 1
        elif b >= 0xF8:
            name = {0xF8: "clock", 0xFA: "start", 0xFB: "continue",
                    0xFC: "stop", 0xFE: "sensing"}.get(b, f"realtime {b:02X}")
            out.append(_m(name, "", data[i:i + 1]))
            i += 1
        elif 0x90 <= b <= 0x9F and i + 2 < n:
            note, vel = data[i + 1], data[i + 2]
            label = INST_LABEL.get(note, f"note {note}")
            kind = "note on" if vel else "note off"
            out.append(_m(kind, f"ch{(b & 15) + 1}  {label}  vel {vel}",
                          data[i:i + 3]))
            i += 3
        elif 0x80 <= b <= 0x8F and i + 2 < n:
            note = data[i + 1]
            out.append(_m("note off",
                          f"ch{(b & 15) + 1}  "
                          f"{INST_LABEL.get(note, f'note {note}')}",
                          data[i:i + 3]))
            i += 3
        elif 0xB0 <= b <= 0xBF and i + 2 < n:
            from .ccmap import label
            out.append(_m("control",
                          f"ch{(b & 15) + 1}  {label(data[i + 1])} = "
                          f"{data[i + 2]}",
                          data[i:i + 3]))
            i += 3
        elif 0xC0 <= b <= 0xCF and i + 1 < n:
            out.append(_m("program", f"ch{(b & 15) + 1}  value {data[i + 1]}",
                          data[i:i + 2]))
            i += 2
        elif 0xE0 <= b <= 0xEF and i + 2 < n:
            out.append(_m("pitchbend", f"ch{(b & 15) + 1}", data[i:i + 3]))
            i += 3
        elif 0xD0 <= b <= 0xDF and i + 1 < n:
            out.append(_m("aftertouch", f"ch{(b & 15) + 1}", data[i:i + 2]))
            i += 2
        else:
            i += 1
    return out


def _m(kind: str, detail: str, raw: bytes) -> dict:
    return {"kind": kind, "detail": detail, "hex": bytes(raw).hex(" ")}
