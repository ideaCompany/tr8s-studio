"""
Layer 3 — the live monitor. Answers "what is the machine doing right now?"

The TR-8S transmits MIDI clock (24 per quarter note) plus Start/Stop, so the
playhead can be followed exactly rather than guessed. Note that **clock
free-runs even while stopped**, so playing state comes from Start/Stop only --
clock presence proves nothing.

Instrument activity is not sniffed from MIDI; it is derived from the pattern
already read over SysEx plus the current step. That is both cheaper and more
accurate, since it reflects what the sequencer holds rather than what happens
to be audible.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

CLOCK, START, CONTINUE, STOP, ACTIVE_SENSE = 0xF8, 0xFA, 0xFB, 0xFC, 0xFE
PULSES_PER_STEP = 6          # 24 ppqn / 4 sixteenths
STEPS_PER_BAR = 16


def detect_edits(known, live, now, fresh=2.3, stale=2.8):
    """
    Diff what is heard against what is known, to spot a panel step edit.

    `known` is {inst: set(step)} for the pattern believed to be playing;
    `live` is {inst: [(vel, when)]*16} of what has actually sounded. A step
    heard recently that we did not know about is one the human just added; a
    step we knew about that has gone silent for over a bar is one they
    removed. Every instrument fires a note per hit, so hearing is proof --
    the machine announces a panel step edit no other way.

    A step is only judged removed once it has been heard at least once
    (`when > 0`); otherwise a step that has not come round yet since the studio
    started would read as absent. Returns (added, removed) as {inst: set(step)}.
    """
    added, removed = {}, {}
    for inst, row in live.items():
        k = known.get(inst, ())
        for st, (vel, when) in enumerate(row):
            if vel and now - when <= fresh and st not in k:
                added.setdefault(inst, set()).add(st)
    for inst, steps in known.items():
        row = live.get(inst)
        if not row:
            continue
        for st in steps:
            if 0 <= st < len(row):
                vel, when = row[st]
                if when > 0 and now - when > stale:
                    removed.setdefault(inst, set()).add(st)
    return added, removed


@dataclass
class MonitorState:
    pattern: int | None = None     # last pattern the device announced
    pattern_channel: int | None = None   # the channel that announcement came on
    pattern_at: float = 0.0        # monotonic time of that announcement
    program_channels: set = None         # every channel a PC has arrived on
    recent_programs: list = None         # [(monotonic, channel, value)] tail
    hits: list = None                    # [(step, instrument)] recently heard
    last_note: float = 0.0               # when the machine last sounded
    recent_cc: list = None               # [(t, channel, cc, value)] tail
    beat: int | None = None              # 0..3 within the bar, from CC 2
    beat_at: float = 0.0                 # when that beat message arrived
    live: dict = None                    # {inst: [(vel, when)]*16} heard
    controls: dict = None                # {cc: (value, when)} last seen
    playing: bool = False
    step: int = 0                 # 0..15 within the bar
    bar: int = 0
    pulse: int = 0                # clocks since the last Start
    bpm: float | None = None
    clock_seen: bool = False
    last_clock: float = 0.0
    started_at: float | None = None

    def controls_moved(self, max_age: float = 1.5) -> dict:
        """Controls touched in the last moment, {cc: value}. Small on purpose:
        it rides on every transport event, so only what just moved."""
        if not self.controls:
            return {}
        now = time.monotonic()
        return {cc: v for cc, (v, when) in self.controls.items()
                if now - when <= max_age}

    def live_rows(self, max_age: float = 2.2) -> dict:
        """
        What is playing right now, as step strings the grid can draw.

        A step counts if it was heard within the last bar or so. That is how a
        variation change or an edit shows up within one pass: steps that stop
        sounding fall out of the picture on their own, with no bookkeeping.
        The window is a shade over one bar at 120 BPM (2.0s); at faster tempos
        it spans a little more than a bar, which only makes it steadier.
        """
        if not self.live:
            return {}
        # ...but a fixed window is wrong at slow tempos: at 82 BPM a bar is
        # 2.9s, so a heard step vanished from the grid mid-bar and came back
        # on its next hit. Cover at least a bar and a bit at the current tempo.
        if self.bpm:
            max_age = max(max_age, 4 * 60.0 / self.bpm * 1.15)
        now = time.monotonic()
        out = {}
        for inst, row in self.live.items():
            chars = []
            for vel, when in row:
                if vel and now - when <= max_age:
                    chars.append("X" if vel >= 112 else "x" if vel >= 80 else "o")
                else:
                    chars.append(".")
            s = "".join(chars)
            if s.strip("."):
                out[inst] = s
        return out

    def live_snapshot(self) -> dict:
        """The raw per-step (vel, when) picture, copied for off-thread diffing.

        `live_rows` collapses to characters and a fixed window; edit detection
        needs the timestamps, to tell a step that has gone silent for a bar
        (removed) from one that simply has not come round yet."""
        if not self.live:
            return {}
        return {inst: list(row) for inst, row in self.live.items()}

    def as_dict(self, light: bool = False) -> dict:
        """
        `light` leaves out the rolling buffers -- hits, the raw trace, recent
        program/control changes. Those are hundreds of tuples, and copying them
        on every step change (sixteen times a bar, on the MIDI thread, then
        serialised to every browser tab) is what made the UI lag.
        """
        if light:
            return {
                "pattern": self.pattern,
                "pattern_channel": self.pattern_channel,
                "pattern_at": self.pattern_at,
                "playing": self.playing,
                "step": self.step,
                "bar": self.bar,
                "beat": self.beat,
                "bpm": round(self.bpm, 1) if self.bpm else None,
                "clock": self.clock_seen,
                "live": self.live_rows() if self.playing else {},
                "controls": self.controls_moved(),
            }
        return {
            "pattern": self.pattern,
            "pattern_channel": self.pattern_channel,
            "pattern_at": self.pattern_at,
            "controls": self.controls_moved(),
            "beat": self.beat,
            "live": self.live_rows() if self.playing else {},
            "program_channels": sorted(self.program_channels or ()),
            "recent_programs": list(self.recent_programs or ()),
            "hits": list(self.hits or ()),
            "recent_cc": list(self.recent_cc or ()),
            "beat": self.beat,
            "live": self.live_rows(),
            "playing": self.playing,
            "step": self.step,
            "bar": self.bar,
            "bpm": round(self.bpm, 1) if self.bpm else None,
            "clock": self.clock_seen,
            "running_for": (round(time.time() - self.started_at, 1)
                            if self.started_at and self.playing else None),
        }


def _clock_period(samples) -> float:
    """
    Seconds per MIDI clock from (index, arrival time) samples.

    Least-squares slope of time against clock index, so a few ms of USB
    jitter on any one sample barely moves it. But arrival times lie whenever
    the reader thread stalls: the clocks that queued up during the stall all
    land at once, with the same late timestamp. Those show up as one long
    interval followed by near-zero ones; every sample on the wrong side of
    that is left out, and the ones that arrived on time keep their true
    index, so the slope is unaffected by the stall.
    """
    pts = list(samples)
    if len(pts) < 8:
        return 0.0
    ivs = [(t - pt) / (k - pk) for (pk, pt), (k, t) in zip(pts, pts[1:])
           if k > pk]
    if not ivs:
        return 0.0
    med = sorted(ivs)[len(ivs) // 2]
    if med <= 0:
        return 0.0
    clean = [pts[i + 1] for i, iv in enumerate(ivs)
             if 0.7 * med <= iv <= 1.3 * med]
    if len(clean) < 6:
        return med
    n = len(clean)
    xm = sum(k for k, _ in clean) / n
    tm = sum(t for _, t in clean) / n
    num = sum((k - xm) * (t - tm) for k, t in clean)
    den = sum((k - xm) ** 2 for k, _ in clean)
    return num / den if den else med


# What each instrument transmits when it sounds, from the TR-8S MIDI
# Implementation Chart (v1.10). Configurable on the machine at
# UTILITY:MIDI:Inst Note, so this is the default and not a guarantee.
INST_NOTES = {36: "BD", 38: "SD", 43: "LT", 47: "MT", 50: "HT", 37: "RS",
              39: "HC", 42: "CH", 46: "OH", 49: "CC", 51: "RC"}


class Monitor:
    """
    Attach to a Transport and track the transport state.

    Thread-safe: the reader thread calls feed(), consumers call snapshot().
    """

    def __init__(self, on_change=None):
        self.state = MonitorState()
        self._lock = threading.Lock()
        # Clock arrival times. USB delivers MIDI in bursts a few ms apart,
        # so the tempo is measured over a long span (145 clocks, six beats)
        # where that jitter is worth a few hundredths of a BPM, not tenths.
        self._times: deque = deque(maxlen=145)     # (clock index, time)
        self._nclock = 0
        self._on_change = on_change
        self._chan_leftover = bytearray()
        self._last_emit = (None, None)
        # note number -> instrument; overridable, since the machine can
        # remap them at UTILITY:MIDI:Inst Note
        self.inst_notes = dict(INST_NOTES)

    # called from the transport reader thread
    def feed(self, data: bytes):
        changed = False
        now = time.time()
        with self._lock:
            s = self.state
            for b in data:
                if b == CLOCK:
                    s.clock_seen = True
                    s.last_clock = now
                    self._nclock += 1
                    self._times.append((self._nclock, now))
                    if len(self._times) >= 8:
                        period = _clock_period(self._times)
                        if period > 0:
                            # 24 clocks per quarter note
                            bpm = 60.0 / (period * 24)
                            # The machine's tempo is steady and has 0.1
                            # resolution; the readout should not wander by a
                            # tenth or two because of delivery jitter. Snap
                            # to 0.1 and move only past a small dead-band --
                            # a real tempo change clears it at once.
                            if 20 < bpm < 400:
                                # the shown value moves only when the raw
                                # estimate is nearer another tenth
                                if s.bpm is None or abs(bpm - s.bpm) > 0.08:
                                    s.bpm = round(bpm, 1)
                    # The TR-8S sends clock continuously, whether or not it is
                    # playing, and it does not echo a Start that we sent
                    # ourselves. Gating the step counter on `playing` left it
                    # frozen at 0, so every note the machine sent was recorded
                    # as landing on step 1. Let it free-run; Start resets the
                    # phase, and anything that needs absolute alignment has to
                    # cope with not having it.
                    if True:
                        s.pulse += 1
                        step = (s.pulse // PULSES_PER_STEP) % STEPS_PER_BAR
                        bar = s.pulse // (PULSES_PER_STEP * STEPS_PER_BAR)
                        if step != s.step:
                            s.step, s.bar, changed = step, bar, True
                elif b in (START, CONTINUE):
                    s.playing = True
                    s.started_at = now
                    if b == START:
                        s.pulse = 0
                        s.step = 0
                        s.bar = 0
                    changed = True
                elif b == STOP:
                    s.playing = False
                    changed = True
        if changed and self._on_change:
            try:
                self._on_change(self.snapshot(light=True))
            except Exception:
                pass

    def feed_channel(self, data: bytes):
        """
        Watch for Program Change, which the TR-8S sends when the user selects a
        pattern (only if Tx Prog Chg is ON -- otherwise this stays silent and
        the UI simply shows no pattern until one is read explicitly).

        The channel matters. The machine has *two* program-change channels:
        `Pattern Ch` for the sequencer and `Kit Ch` for switching kits. Both
        carry a number 0-127, so a kit change is indistinguishable from a
        pattern change by content alone -- only the channel separates them.
        Every channel a PC has arrived on is recorded so the ambiguity can be
        seen rather than guessed at.
        """
        changed = False
        i = 0
        # A channel message can be split across payloads: the reader hands over
        # channel bytes in arrival order, and a realtime byte (a clock, while
        # playing) between a status byte and its data ends one payload and
        # starts the next. Parsed per-payload, the two halves were both
        # dropped -- which is why Program Change (pattern-follow) silently
        # stopped working the moment the machine was playing. Carry any
        # trailing incomplete message over to the next call so it reassembles.
        data = bytes(self._chan_leftover) + bytes(data)
        self._chan_leftover = bytearray()
        with self._lock:
            if self.state.program_channels is None:
                self.state.program_channels = set()
            if self.state.recent_programs is None:
                self.state.recent_programs = []
            while i < len(data):
                b = data[i]
                if b < 0x80:
                    i += 1                      # stray data byte, no status
                    continue
                if b >= 0xF0:
                    i += 1                      # system/realtime, not ours
                    continue
                mlen = 2 if 0xC0 <= b <= 0xDF else 3   # PC/chan-pressure vs rest
                if i + mlen > len(data):
                    self._chan_leftover = bytearray(data[i:])  # finish next time
                    break
                if 0x90 <= b <= 0x9F:
                    # a note-on is the machine telling us what just sounded;
                    # paired with the clock's step it says what is playing
                    note, vel = data[i + 1], data[i + 2]
                    inst = self.inst_notes.get(note)
                    if vel and inst:
                        # a note is the machine telling us it is playing --
                        # more reliable than Start, which we never see when we
                        # started it ourselves
                        self.state.playing = True
                        self.state.last_note = time.monotonic()
                        # the live picture: what is actually sounding, step by
                        # step, for the grid to show as it happens
                        if self.state.live is None:
                            self.state.live = {}
                        row = self.state.live.setdefault(
                            inst, [(0, 0.0)] * 16)
                        now_m = time.monotonic()
                        st = self.state.step % 16
                        # a note on the step we just left, within 60ms, is
                        # the same hit seen across the anchor boundary, not a
                        # second one -- keep it where it was
                        prev = (st - 1) % 16
                        if row[prev][0] and now_m - row[prev][1] < 0.06:
                            st = prev
                        row[st] = (vel, now_m)
                        if self.state.hits is None:
                            self.state.hits = []
                        self.state.hits.append(
                            (time.monotonic(), self.state.step, inst))
                        del self.state.hits[:-256]
                        changed = True
                    i += mlen
                elif 0xB0 <= b <= 0xBF:
                    # Control Change. With UTILITY:MIDI:Tx EditData ON the
                    # machine sends these when a knob or fader is moved, which
                    # is the one kind of panel edit it does announce.
                    if self.state.recent_cc is None:
                        self.state.recent_cc = []
                    self.state.recent_cc.append(
                        (round(time.monotonic(), 3), b & 0x0F,
                         data[i + 1], data[i + 2]))
                    del self.state.recent_cc[:-64]
                    # every panel control, by CC, with its last value: this
                    # is what moves the knobs and faders on screen
                    if self.state.controls is None:
                        self.state.controls = {}
                    self.state.controls[data[i + 1]] = (data[i + 2],
                                                        time.monotonic())
                    # CC 2 is the beat within the bar, 0..3, sent on every
                    # beat while playing (with Tx EditData on). Measured: it
                    # lands within 10 ms of the downbeat kick every time. It is
                    # the bar phase this code had been guessing at by trying
                    # sixteen rotations -- the machine says it outright.
                    if data[i + 1] == 2 and data[i + 2] < 4:
                        self.state.beat = data[i + 2]
                        self.state.beat_at = time.monotonic()
                        # The beat counter only ticks while the sequencer
                        # runs, so it is proof of playing even when nothing
                        # sounds -- an empty pattern being built from scratch
                        # sends no notes at all. Without this the studio
                        # thought such a pattern was stopped, polled it, and
                        # the bulk read hung the port for 25s.
                        self.state.playing = True
                        # re-anchor the free-running step counter to the bar.
                        # The CC arrives ~5ms AFTER the downbeat notes, so the
                        # kick at beat 0 was already recorded under the old
                        # (possibly wrong) step; set pulse to the beat's first
                        # clock exactly so the following notes land right.
                        self.state.pulse = data[i + 2] * PULSES_PER_STEP * 4
                        self.state.step = data[i + 2] * 4
                    changed = True
                    i += mlen
                elif 0xC0 <= b <= 0xCF:
                    self.state.pattern = data[i + 1]
                    self.state.pattern_channel = b & 0x0F
                    self.state.pattern_at = time.monotonic()
                    self.state.program_channels.add(b & 0x0F)
                    self.state.recent_programs.append(
                        (time.monotonic(), b & 0x0F, data[i + 1]))
                    del self.state.recent_programs[:-24]
                    changed = True
                    i += mlen
                else:
                    i += mlen                   # note-off, aftertouch, bend
        if changed and self._on_change:
            try:
                self._on_change(self.snapshot(light=True))
            except Exception:
                pass

    def snapshot(self, light: bool = False) -> dict:
        with self._lock:
            # clock can stop arriving if the cable is pulled
            if self.state.clock_seen and time.time() - self.state.last_clock > 2.0:
                self.state.clock_seen = False
                self.state.bpm = None
            # playing is inferred from notes and the beat counter, so it has
            # to lapse on silence -- silence from both
            last = max(self.state.last_note or 0.0, self.state.beat_at or 0.0)
            if (self.state.playing and last
                    and time.monotonic() - last > 2.0):
                self.state.playing = False
            return self.state.as_dict(light=light)

    def reset(self):
        with self._lock:
            self.state = MonitorState()
            self._times.clear()


def active_instruments(variation_tracks: dict, step: int) -> list[str]:
    """
    Which instruments fire on a given step, from pattern data already read.

    `variation_tracks` is {instrument: "X...x..."} as Pattern.variation_summary
    returns.
    """
    out = []
    for inst, steps in (variation_tracks or {}).items():
        if step < len(steps) and steps[step] != ".":
            out.append(inst)
    return out
