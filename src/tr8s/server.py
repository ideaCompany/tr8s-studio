"""
Layer 4 — the studio server. Serves the web UI and bridges it to the device.

Stdlib only: ThreadingHTTPServer plus Server-Sent Events for live updates.
SSE rather than WebSockets because the live traffic is one-directional (device
-> browser) and SSE reconnects on its own.

    tr8s-studio                 # http://127.0.0.1:8733

Routes
    GET  /                      the UI
    GET  /static/*              assets
    GET  /api/state             device + transport snapshot (+ cached pattern)
    GET  /api/events            SSE stream: transport, pattern, chat events
    GET  /api/tools             tool schemas
    POST /api/tool              {name, args} -> result
    POST /api/chat              {message} -> {reply}; progress arrives via SSE
    POST /api/select            {slot} -> read that pattern and cache it
"""

from __future__ import annotations

import json
import re
import queue
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from . import agent as agentmod
from .device import DeviceError, slot_to_panel
from . import melody as melodymod
from .history import HISTORY
from .monitor import Monitor, active_instruments
from .transport import TransportError
from .ccmap import describe as cc_describe, label as cc_label, to_kit_value
from .changelog import CHANGELOG
from .fingerprint import Index, heard_set
from .monitor import detect_edits
from .midilog import MidiLog
from .pattern import TRACKS, VARIATIONS, Pattern
from .tools import REGISTRY, ToolError
from .tools import call as tool_call
from .tools import close as _tool_close
from .tools import close as tool_close
from .tools import device as tool_device
from .tools import schemas

WEB = Path(__file__).parent / "web"
DEFAULT_PORT = 8733


class Hub:
    """Fan-out of events to every connected browser."""

    def __init__(self):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass          # a slow client must not stall the device


class Studio:
    def __init__(self):
        self.hub = Hub()
        self.monitor = Monitor(on_change=self._on_transport)
        # a visible answer to "is any MIDI arriving, and what?"
        self.midilog = MidiLog()
        self.chat = None
        self.chat_error = None
        self.chat_backend = None
        self._login = None
        self.connected = False
        self.info = {}
        self.slot = None
        self.pattern = None       # cached describe() of the selected pattern
        self.pattern_obj = None   # the live Pattern, so step edits skip a read
        self.kit = None           # the pattern's kit, with tone names resolved
        self.index: dict[int, dict] = {}   # slot -> {name, tempo, kit}
        self.index_state = "idle"          # idle | building | ready
        self._watchdog = None
        self._lock = threading.Lock()
        self._last_step = -1
        # following the machine's own pattern changes
        self.follow = True
        # None = follow a Program Change on any channel. Set it once the
        # machine's Pattern Ch is known, so that switching a KIT (which sends
        # its own Program Change on Kit Ch) cannot drag the view to an
        # unrelated pattern.
        # learned once and remembered: rediscovering it after every restart
        # means the user has to change a pattern before following works
        saved = config.load_settings()
        self.pattern_channel: int | None = saved.get("pattern_channel")
        self.kit_channel: int | None = saved.get("kit_channel")
        self.seen_program_change = False
        self._pc_handled = 0.0        # monotonic time of the last PC acted on
        self._print_tries: dict[int, int] = {}   # slots read for a missing print
        self._want_slot: int | None = None
        self._pending: list = []
        self._follow_wake = threading.Event()
        self._follower = None
        # reading the pattern back, so edits made ON the machine show up here
        self.follow_variation = True
        self.heard_variation = None
        self._last_guess = 0.0
        # Fingerprints of every pattern's variations. Built once, cached, and
        # then identification is arithmetic -- no reads, so no interference
        # with the clock and nothing for the UI to wait on.
        self.prints = Index.load(config.data_dir() / "fingerprints.json")
        self.prints_state = "ready" if len(self.prints) else "empty"
        self.heard_slot = None
        self._var_candidate = None    # (slot, variation) seen on the last check
        self.busy = False             # a local write is in flight
        self.last_sync = None
        self._sync_wake = threading.Event()
        self._syncer = None
        self._want_resync = None
        self.follow_edits = True      # poll for panel step-edits while stopped
        self._live_pending = set()    # insts whose live add not yet re-read
        self._live_seen = set()       # (inst, step) already reported live
        self._live_slot = None
        self._last_live_check = 0.0
        # By-ear step detection while playing is best-effort: on clean drum
        # patterns it is reliable, but rolls, sub-steps and pitched voices make
        # the heard grid diverge from the stored one, so it is off by default
        # and never pollutes the log unless the user opts in.
        self.live_by_ear = False
        # TRACK-focus by ear while playing. Exact step detection by ear is
        # unreliable (rolls, sub-steps, swing) -- but those are the SAME bar
        # after bar, so an instrument whose heard steps differ from its own
        # previous bars is one somebody just edited. This only moves TRACK;
        # the exact edit is logged by the read on stop.
        self.focus_by_ear = True
        self._ear_focus: dict[str, float] = {}   # inst -> when last focused
        self._ear_seen = set()        # (inst, step, kind) seen last check
        self._ear_reported: dict = {} # (inst, step, kind) -> when reported
        # The machine holds edits the studio has only heard, not read. A
        # studio write now would push stale bytes over them.
        self._panel_dirty = False
        # Recognition and ear-focus are pure Python over hundreds of sets.
        # Run on the MIDI thread they stalled the reader for ~200ms at a
        # time: clocks queued up and arrived bunched, and the tempo readout
        # wandered by a BPM. They run on their own thread, woken from here.
        self._listen_wake = threading.Event()
        self._listener = None
        self._listen_jobs: list = []
        self._last_ear_check = 0.0

    # ------------------------------------------------------------- device

    def connect(self) -> bool:
        try:
            dev = tool_device()

            def realtime(data):
                self.midilog.feed(data)
                self.monitor.feed(data)

            def channel(data):
                self.midilog.feed(data)
                self.monitor.feed_channel(data)

            dev.transport.on_realtime = realtime
            dev.transport.on_channel = channel
            dev.playing = lambda: self.monitor.snapshot(light=True).get("playing")
            self._watch_writes(dev)
            self.info = dev.info()
            self.connected = True
        except Exception as e:
            self.connected = False
            self.info = {"error": str(e)}
        return self.connected

    def _watch_writes(self, dev):
        """
        Keep the fingerprint index current with every pattern the studio
        writes or reads. `Device.remember` is the one place every write and
        read passes through, so wrapping it means a track the assistant just
        built is recognisable by ear at once -- before, its slot kept the OLD
        pattern's fingerprint until the machine stopped and the slot was
        re-read, and the variation readout stayed dead while it played.
        """
        if getattr(dev, "_tr8s_watched", False):
            return
        orig = getattr(dev, "remember", None)
        if orig is None:
            return

        def remember(kind, slot, blob):
            orig(kind, slot, blob)
            if kind != "pattern" or not len(self.prints):
                return
            try:
                p = Pattern.from_bytes(blob)
                self.prints.add(int(slot), p.name,
                                {v: p.variation_summary(v) for v in VARIATIONS})
                self._prints_dirty = True
                if int(slot) == self.slot:
                    self.heard_variation = None     # hear it afresh
            except Exception:
                pass

        dev.remember = remember
        dev._tr8s_watched = True

    def _save_prints_if_dirty(self):
        if getattr(self, "_prints_dirty", False):
            self._prints_dirty = False
            try:
                self.prints.save(config.data_dir() / "fingerprints.json")
            except Exception:
                pass

    def start_watchdog(self, period: float = 4.0):
        """
        Reconnect on its own after the TR-8S is unplugged and plugged back in.

        Without this the studio stays dead until restarted, which is a poor
        showing for a device people physically move around.
        """
        def run():
            while True:
                time.sleep(period)
                if self.connected:
                    continue
                try:
                    _tool_close()             # drop the stale port handle
                except Exception:
                    pass
                if self.connect():
                    self.hub.publish({"type": "hello", **self.state()})
                    if self.slot is not None:
                        try:
                            self.select(self.slot)
                        except Exception:
                            pass
        if self._watchdog is None:
            self._watchdog = threading.Thread(target=run, daemon=True,
                                              name="tr8s-watchdog")
            self._watchdog.start()

    # ------------------------------------------- which variation is playing

    def _recognise(self, hits):
        """Identify what is playing, and move the view onto it."""
        heard = heard_set(hits)
        if len(heard) < 4:
            return
        m = None
        if len(self.prints):
            # prefer the pattern already on screen: several patterns can share
            # a groove, and jumping away from the one being edited is worse
            # than staying put
            if self.slot is not None:
                m = self.prints.identify(heard, only=self.slot)
            # A machine that announces its pattern (Program Change on a
            # known pattern channel -- learned once, saved) is the truth, and
            # the ear only picks the variation within it. Letting a by-ear
            # match move the slot as well dragged the view off the machine's
            # real pattern onto a look-alike: after a restart, before any PC
            # had arrived, an edited 8-06 no longer matched its own print and
            # the studio wandered off to "727 Variation 1". The channel is
            # enough; waiting for the first PC of the session is not.
            announced = self.pattern_channel is not None
            if m is None and not announced:
                m = self.prints.identify(heard)
        if m is None:
            return
        # Sibling variations score close together, and a bar window that
        # straddles a change can favour either for one check. Move only when
        # two consecutive checks agree.
        cand = (m.slot, m.variation)
        if cand != self._var_candidate and cand != (self.heard_slot, self.heard_variation):
            self._var_candidate = cand
            return
        self._var_candidate = cand

        if m.slot != self.slot and self.follow:
            self._want_slot = m.slot
            self._follow_wake.set()
            self.hub.publish({"type": "log", "level": "sys",
                              "message": f"recognised {m.name} "
                                         f"({slot_to_panel(m.slot)}) from what "
                                         f"it is playing"})
        slot_changed = m.slot != self.heard_slot
        self.heard_slot = m.slot
        if m.variation != self.heard_variation or slot_changed:
            self.heard_variation = m.variation
            with self._lock:
                if self.pattern is not None:
                    self.pattern["view_variation"] = m.variation
            self.hub.publish({"type": "variation", "variation": m.variation,
                              "confidence": round(m.score, 2),
                              "slot": m.slot, "heard": True})

    def _detect_live_edits(self):
        """
        Notice a step added on the panel while the machine plays.

        A toggled step is announced by nothing over MIDI and a bulk read hangs
        during playback -- but an armed step fires a note every time the
        playhead reaches it. Hearing is the only in-playback signal, and it is
        imprecise: swing and MIDI latency push a hit onto the neighbouring
        step, pitched voices scatter across notes, and the bar boundary spills
        a downbeat onto the last step. Every false positive those produce sits
        *next to* a real step -- so the rule that makes this reliable is:

          a step counts as newly added only if it is heard on every recent
          bar, is not a pitched voice, is not part of a whole-column glitch,
          and has no known step within one position of it.

        That last clause collapses all the ±1 jitter. The cost is that a step
        added right beside an existing one is missed live (it surfaces on the
        next stop instead); the gain is that what it does report is real.
        Removals and pitched edits are left to the read on stop, which is
        exact. The baseline is never mutated here -- corrupting it would make
        the detector oscillate against its own output.
        """
        with self._lock:
            pat = self.pattern
            slot = self.slot
        if not pat or not pat.get("variations") or slot is None:
            return
        if slot != self._live_slot:         # moved to another pattern
            self._live_seen.clear()
            self._live_slot = slot
        var = (self.heard_variation or pat.get("view_variation")
               or next(iter(pat["variations"]), None))
        if var is None:
            return
        rows = pat["variations"].get(var, {})
        known = {inst: {i for i, c in enumerate(s2) if c != "."}
                 for inst, s2 in rows.items()}
        melodic = set((pat.get("melodies") or {}).get(var, {}) or {})
        bpm = self.monitor.state.bpm or 130.0
        bar = 4 * 60.0 / bpm
        now = time.monotonic()
        hits = self.monitor.snapshot().get("hits") or []
        window = now - bar * 4.2
        bars = {}
        allbars = set()
        for when, st, inst in hits:
            if when < window:
                continue
            b = int(when / bar)
            allbars.add(b)
            bars.setdefault((inst, st), set()).add(b)
        nb = len(allbars)
        if nb < 4:                          # too little evidence yet
            return
        count = {k: len(v) for k, v in bars.items()}

        def near_known(inst, st):
            k = known.get(inst, ())
            return any((st + d) % 16 in k for d in (-1, 0, 1))

        # candidate adds: heard every recent bar, not pitched, isolated from
        # any known step (which soaks up the ±1 jitter)
        cand = {}
        for (inst, st), c in count.items():
            if inst in melodic:
                continue
            if c < nb:                      # not heard on every bar -> sporadic
                continue
            if near_known(inst, st):        # jitter around a real step
                continue
            if (inst, st) in self._live_seen:
                continue
            cand.setdefault(inst, set()).add(st)

        # a whole-column glitch hits several instruments on the same step; a
        # human edits one at a time
        col = {}
        for steps in cand.values():
            for st in steps:
                col[st] = col.get(st, 0) + 1
        artifacts = {st for st, n in col.items() if n >= 3}
        cand = {i: {st for st in steps if st not in artifacts}
                for i, steps in cand.items()}
        cand = {i: steps for i, steps in cand.items() if steps}
        if not cand:
            return

        changed = []
        for inst in sorted(cand):
            a = sorted(cand[inst])
            for st in a:
                self._live_seen.add((inst, st))
            self._live_pending.add(inst)
            CHANGELOG.add("user", "steps", instrument=inst,
                          detail="+" + ",".join(str(x + 1) for x in a)
                                 + " (live)", slot=slot)
            changed.append(inst)
        # the live overlay already shows the step; just move TRACK there and
        # note who did it. The exact pattern is persisted by the read on stop.
        self.hub.publish({"type": "log", "level": "sys",
                          "message": "picked up a step added on the machine "
                                     f"({', '.join(changed)})"})
        self.hub.publish({"type": "pattern", "pattern": dict(pat),
                          "from_machine": True, "changed": changed})

    def _focus_by_ear(self):
        """
        While playing, bring TRACK to the instrument whose part just changed.

        Compares what each instrument sounded in the last bar with what it
        sounded in the two bars before: a step heard now with nothing within
        one position of it before is new; a step heard in both earlier bars
        with nothing within one position of it now is gone. Rolls, sub-steps
        and swing repeat identically every bar, so they cancel out -- which is
        what the heard-vs-STORED comparison could never do. A change on
        several instruments at once is a variation or pattern change, not a
        hand on one row, and is ignored.
        """
        bpm = self.monitor.state.bpm or 0.0
        if bpm < 20:
            return
        bar = 4 * 60.0 / bpm
        now = time.monotonic()
        hits = self.monitor.snapshot().get("hits") or []
        # The current-bar window is a shade over a bar. A hit that lands
        # exactly on the window's edge would otherwise fall out of it for one
        # tick and read as "removed" -- a CH on step 13 was reported gone
        # while nobody touched CH. With the overlap every step is inside.
        w = bar * 1.15
        last, prev1, prev2 = {}, {}, {}
        oldest = now
        for when, st, inst in hits:
            age = now - when
            oldest = min(oldest, when)
            if age <= w:
                last.setdefault(inst, set()).add(st % 16)
            elif age <= w + bar:
                prev1.setdefault(inst, set()).add(st % 16)
            elif age <= w + 2 * bar:
                prev2.setdefault(inst, set()).add(st % 16)
        if now - oldest < 3 * bar - 0.25:
            return                          # not three bars of evidence yet

        # Exact positions, no tolerance. Measured against the machine's own
        # beat counter: every hit is stamped on the first clock of its step,
        # so a step heard at 4 IS step 4. A +-1 tolerance here (a leftover
        # from before that was known) swallowed every edit made next to an
        # existing step -- SD 4 added beside 1, 2, 3 never registered.
        changed = {}
        for inst in set(last) | set(prev1) | set(prev2):
            L = last.get(inst, set())
            P = prev1.get(inst, set()) | prev2.get(inst, set())
            both = prev1.get(inst, set()) & prev2.get(inst, set())
            added = L - P
            removed = both - L
            if added or removed:
                changed[inst] = (added, removed)
        if len(changed) > 2:
            self._ear_seen = set()      # a variation change, not a hand
            return
        # Confirm per STEP, not per change: a hand keeps editing, so the
        # change as a whole is different on every check and would never be
        # "the same twice" -- while each individual step stays. A step counts
        # once it has been a candidate on two consecutive checks, and is
        # reported once.
        cands = set()
        for inst, (added, removed) in changed.items():
            cands.update((inst, st, "+") for st in added)
            cands.update((inst, st, "-") for st in removed)
        confirmed = cands & self._ear_seen
        self._ear_seen = cands
        fresh = {c for c in confirmed
                 if now - self._ear_reported.get(c, 0.0) > 2 * w}
        if not fresh:
            return
        for c in fresh:
            self._ear_reported[c] = now
        for inst in sorted({c[0] for c in fresh}):
            added = {st for i, st, k in fresh if i == inst and k == "+"}
            removed = {st for i, st, k in fresh if i == inst and k == "-"}
            self._report_heard(inst, added, removed)

    def _report_heard(self, inst, added, removed):
        """
        Playing is the normal state, and a stop is a technical detail the
        user should not have to think about: what was heard becomes the
        pattern on screen right now, and is logged right now. The exact read
        on stop reconciles quietly (a heard step can sit one position off at
        a beat boundary).
        """
        merged = self._merge_heard(inst, added, removed)
        bits = []
        if added:
            bits.append("+" + ",".join(str(s + 1) for s in sorted(added)))
        if removed:
            bits.append("-" + ",".join(str(s + 1) for s in sorted(removed)))
        CHANGELOG.add("user", "steps", instrument=inst,
                      detail=" ".join(bits) + " (heard)", slot=self.slot)
        self._live_pending.add(inst)
        self._panel_dirty = True
        self.hub.publish({"type": "focus", "instrument": inst, "how": "heard",
                          "added": sorted(s + 1 for s in added),
                          "removed": sorted(s + 1 for s in removed)})
        if merged is not None:
            self.hub.publish({"type": "pattern", "pattern": merged,
                              "from_machine": True, "changed": [inst],
                              "provisional": True})
        self.hub.publish({"type": "log", "level": "sys",
                          "message": f"{inst} changed on the machine"})

    def _refuse_stale_write(self):
        """
        The one limitation the user has to hear about, at the moment it bites:
        the machine holds edits made on the panel while playing that the
        studio has only heard. A write now would carry stale bytes over them.
        Reading is impossible until the machine stops, so say exactly that.
        """
        if (self._panel_dirty
                and self.monitor.snapshot(light=True).get("playing")):
            insts = ", ".join(sorted(self._live_pending)) or "the machine"
            raise DeviceError(
                f"edits made on the machine ({insts}) have not been read yet "
                f"-- the TR-8S only allows that while stopped. Stop it for a "
                f"moment, then edit here; writing now would overwrite them.")

    def _merge_heard(self, inst: str, added, removed):
        """Put heard steps into the pattern on screen (and the cached model,
        so a studio write carries them). Returns the view, or None."""
        with self._lock:
            pat = self.pattern
            if not pat or pat.get("variations") is None:
                return None
            var = (self.heard_variation or pat.get("view_variation")
                   or next(iter(pat["variations"]), None) or "A")
            rows = pat["variations"].setdefault(var, {})
            row = list(rows.get(inst, "").ljust(16, "."))
            for s in added:
                if row[s] == ".":
                    row[s] = "x"
            for s in removed:
                row[s] = "."
            rows[inst] = "".join(row)
            p = self.pattern_obj
            if p is not None:
                try:
                    p.set_steps(var, inst, rows[inst])
                except Exception:
                    pass
            # the fingerprint follows the edit too, so the variation is still
            # recognised after the hand has changed it
            try:
                if len(self.prints) and pat.get("slot") is not None:
                    self.prints.add(int(pat["slot"]), pat.get("name") or "",
                                    dict(pat["variations"]))
                    self._prints_dirty = True
            except Exception:
                pass
            return dict(pat)

    def build_fingerprints(self, lo: int = 0, hi: int = 127):
        """
        Read every pattern once and remember the shape of its variations.

        A minute of reading buys recognition that costs nothing afterwards --
        which is the difference between following the machine and polling it.
        """
        def run():
            self.prints_state = "building"
            self.hub.publish({"type": "prints", "state": "building",
                              "have": len(self.prints)})
            dev = tool_device()
            ix = Index()
            for slot in range(lo, hi + 1):
                if self.busy:
                    time.sleep(0.5)
                try:
                    p = dev.read_pattern(slot)
                except Exception:
                    continue
                ix.add(slot, p.name,
                       {v: p.variation_summary(v) for v in VARIATIONS})
                if slot % 16 == 15:
                    self.hub.publish({"type": "prints", "state": "building",
                                      "have": len(ix), "at": slot})
            self.prints = ix
            self.prints_state = "ready"
            try:
                ix.save(config.data_dir() / "fingerprints.json")
            except Exception:
                pass
            self.hub.publish({"type": "prints", "state": "ready",
                              "have": len(ix)})
        if self.prints_state != "building":
            threading.Thread(target=run, daemon=True,
                             name="tr8s-prints").start()

    def start_after_stop_reader(self):
        """
        One job: when the machine stops, read what it was playing.

        Bulk reads hang during playback (docs/PROTOCOL.md), so anything that
        wanted a read while the machine played -- an edit heard by ear, a
        pattern recognised but only shown from the fingerprint index -- is
        queued in `_want_resync`, and this is what drains it. It is not a
        poll: it wakes on the transition to stopped and otherwise sleeps.
        """
        def run():
            was_playing = False
            last_poll = 0.0
            while True:
                time.sleep(0.5)
                playing = bool(self.monitor.snapshot(light=True).get("playing"))
                stopped_now = was_playing and not playing
                was_playing = playing
                if playing or self.busy or not self.connected:
                    continue
                slot = self._want_resync
                self._want_resync = None
                if slot is None and stopped_now:
                    slot = self.slot
                # While stopped, poll gently: this is how a step entered on the
                # panel (which sends nothing over MIDI) is noticed. A read is
                # ~0.6s and disturbs nothing while stopped, so every few
                # seconds is invisible. It never runs during playback.
                now = time.monotonic()
                if slot is None and self.follow_edits and now - last_poll > 1.6:
                    last_poll = now
                    slot = self.slot
                if slot is None:
                    self._save_prints_if_dirty()
                    # idle and stopped: a good moment to read a pattern the
                    # fingerprint index is missing, one per pass
                    if self.follow_edits:
                        try:
                            self._fill_one_print()
                        except Exception:
                            pass
                    continue
                try:
                    self._resync(slot)
                    if len(self.prints):
                        self._reprint(slot)
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True, name="tr8s-after-stop").start()

    def missing_prints(self) -> list[int]:
        """Slots the fingerprint index has never managed to read."""
        if self.prints_state != "ready" or not len(self.prints):
            return []
        return [s for s in range(128)
                if s not in self.prints.entries
                and self._print_tries.get(s, 0) < 2]

    def _fill_one_print(self) -> bool:
        """
        Read one pattern the index is missing, so the machine can be followed
        onto it while playing. The build skips any read that fails (it may
        have run while the machine played); without this those slots stay
        unfollowable for the rest of the session. One read per call, stopped
        only, so it never competes with the edit poll for long.
        """
        missing = self.missing_prints()
        if not missing:
            return False
        slot = missing[0]
        self._print_tries[slot] = self._print_tries.get(slot, 0) + 1
        try:
            p = tool_device().read_pattern(slot)
        except Exception:
            return True                # counted; it gets one more try
        self.prints.add(slot, p.name,
                        {v: p.variation_summary(v) for v in VARIATIONS})
        try:
            self.prints.save(config.data_dir() / "fingerprints.json")
        except Exception:
            pass
        return True

    def _reprint(self, slot: int):
        """Keep the fingerprint of a changed pattern current."""
        with self._lock:
            p = self.pattern_obj
        if p is not None:
            self.prints.add(slot, p.name,
                            {v: p.variation_summary(v) for v in VARIATIONS})
            try:
                self.prints.save(config.data_dir() / "fingerprints.json")
            except Exception:
                pass

    def _resync(self, slot: int) -> bool:
        """
        Re-read one pattern; publish if the machine changed it.

        This is the only way a step entered on the panel is ever seen -- the
        machine sends nothing for it -- so it also works out *which*
        instruments changed, so the studio can bring TRACK to the one being
        worked on. It always makes `slot` the studio's current pattern: the
        machine is on it, and the stopped-poll must keep reading the pattern
        the machine is on, not the one the studio happened to show before.
        """
        dev = tool_device()
        # exact prior bytes if we hold them. Never `dev.snapshot`, which reads
        # the slot when it is not cached -- that made every first read of a
        # followed pattern cost two reads and compare a blob to itself.
        known = dev._blobs.get(("pattern", slot))
        blob = dev.transport.read_blob("pattern", slot)
        self.last_sync = time.time()
        if not blob:
            return False
        with self._lock:
            shown = self.pattern or {}
            showing_index_view = (bool(shown.get("from_index"))
                                  and shown.get("slot") == slot)
            shown_steps = ({v: dict(r) for v, r
                            in (shown.get("variations") or {}).items()}
                           if showing_index_view else None)
        # unchanged bytes are still worth publishing if what is on screen is
        # the steps-only view from the fingerprint index: it has no header,
        # and this read is the first chance to replace it with the real thing
        if blob == known and not showing_index_view:
            return False
        # Baseline to diff against: the exact prior bytes if we hold them
        # (full accent detail). Otherwise the studio followed the machine here
        # while it played and is showing the fingerprint-index view (steps
        # only) or a bare placeholder (an empty or never-read slot): diff
        # against that, presence only. An index entry is refreshed on every
        # read, so it is only stale when the pattern changed while the studio
        # was not watching -- and reporting that difference once is still
        # useful. What must never happen is inventing an edit out of a
        # baseline that is simply unknown, so a presence-only diff touching
        # many instruments at once is treated as an unknown baseline and
        # establishes it silently instead.
        base_steps = None
        presence_only = False
        if known and known != blob:
            try:
                base_steps = {v: Pattern.from_bytes(known).variation_summary(v)
                              for v in VARIATIONS}
            except Exception:
                base_steps = None
        elif known is None and shown_steps is not None:
            base_steps, presence_only = shown_steps, True
        changed_inst = []
        if base_steps is not None:
            try:
                new_p = Pattern.from_bytes(blob)
                found = []
                for inst in TRACKS:
                    added = removed = edited = 0
                    for v in VARIATIONS:
                        o = base_steps.get(v, {}).get(inst, "")
                        n = new_p.variation_summary(v).get(inst, "")
                        if o == n:
                            continue
                        for a_, b_ in zip(o.ljust(16, "."), n.ljust(16, ".")):
                            if a_ == b_:
                                continue
                            if a_ == ".":
                                added += 1
                            elif b_ == ".":
                                removed += 1
                            elif not presence_only:
                                edited += 1        # accent/ghost change
                    if added or removed or edited:
                        found.append((inst, added, removed, edited))
                if presence_only and len(found) > 5:
                    found = []      # not one person's edit: unknown baseline
                for inst, added, removed, edited in found:
                    changed_inst.append(inst)
                    if inst in self._live_pending:
                        continue   # already logged live; the read confirms it
                    bits = []
                    if added:
                        bits.append(f"+{added}")
                    if removed:
                        bits.append(f"-{removed}")
                    if edited:
                        bits.append(f"~{edited}")
                    n_ch = added + removed + edited
                    CHANGELOG.add("user", "steps", instrument=inst,
                                  detail=" ".join(bits) + " step"
                                         + ("s" if n_ch != 1 else ""),
                                  slot=slot)
            except Exception:
                pass
        dev.remember("pattern", slot, blob)
        p = Pattern.from_bytes(blob)
        d = p.describe()
        d.update(slot=slot, panel=slot_to_panel(slot))
        # A view born while the machine played came from the fingerprint
        # index with no kit at all. This is the first read since it stopped,
        # so resolve the kit now -- otherwise the SOUND bar and the strips
        # stay empty until something else happens to re-select.
        kit = self.kit
        if kit is None or kit.get("_slot") != p.kit:
            try:
                kit = tool_call("kit.get", {"slot": p.kit})
                kit["_slot"] = p.kit
            except Exception:
                kit = self.kit
        with self._lock:
            self.slot = slot
            self.pattern_obj = p
            self.kit = kit
            d["melodies"] = self._melodies(p, kit)
            self.pattern = d
        self.hub.publish({"type": "pattern", "pattern": d, "kit": kit,
                          "history": self._history(),
                          "from_machine": True, "changed": changed_inst})
        fresh = [i for i in changed_inst if i not in self._live_pending]
        msg = None
        if fresh:
            msg = (f"picked up an edit made on the machine "
                   f"({slot_to_panel(slot)}: {', '.join(fresh)})")
        elif changed_inst:
            msg = None          # only confirming what was already heard
        elif known is not None and known != blob:
            msg = f"picked up a change made on the machine ({slot_to_panel(slot)})"
        elif showing_index_view:
            msg = f"read {slot_to_panel(slot)} from the machine"
        if msg:
            self.hub.publish({"type": "log", "level": "sys", "message": msg})
        self._live_pending.clear()
        self._live_seen.clear()
        self._panel_dirty = False
        return True

    def _learn_channel(self):
        """
        Work out which MIDI channel carries the pattern.

        Changing a pattern makes the machine announce two things at once: the
        pattern on `Pattern Ch` and its kit on `Kit Ch`. Both are a bare 0-127,
        so nothing in the messages themselves says which is which -- and
        following the kit number lands the view on an unrelated pattern.

        What separates them is that the numbers are not independent: the kit
        announcement should equal the kit reference stored *inside* the pattern
        the other message names. So read the candidates and see which way round
        that holds. One read settles it for the session.
        """
        burst = [p for p in (self._pending or [])]
        self._pending = []
        if len(burst) < 2:
            return
        recent = burst[-6:]
        latest = recent[-1][0]
        recent = [p for p in recent if latest - p[0] < 1.5]
        pairs = {ch: val for _, ch, val in recent}
        if len(pairs) < 2:
            return

        dev = tool_device()
        for ch, val in pairs.items():
            others = {c: v for c, v in pairs.items() if c != ch}
            try:
                p = dev.read_pattern(val)
            except Exception:
                continue
            if p.kit in others.values():
                self.pattern_channel = ch
                self.kit_channel = next(c for c, v in others.items()
                                        if v == p.kit)
                config.save_settings({"pattern_channel": self.pattern_channel,
                                      "kit_channel": self.kit_channel})
                self.hub.publish({
                    "type": "log", "level": "sys",
                    "message": (f"learned the pattern channel: "
                                f"{ch + 1} (kit changes arrive on "
                                f"{self.kit_channel + 1})")})
                self._want_slot = val
                return
        # nothing matched -- say so rather than following a coin flip
        self.hub.publish({
            "type": "log", "level": "err",
            "message": ("two program changes arrived and neither names a "
                        "pattern whose kit matches the other, so which is "
                        "which is unclear. Pin the channel from the FOLLOW "
                        "dialog.")})

    def mark_disconnected(self, err: Exception):
        if self.connected:
            self.connected = False
            self.info = {"error": str(err)}
            self.hub.publish({"type": "hello", **self.state()})

    def _on_control(self, moved: dict):
        """
        A knob or fader moved on the panel. Push it, and keep the studio's
        copy of the kit in step so the on-screen knob does not snap back the
        next time something redraws it.
        """
        changes = []
        playing = self.monitor.snapshot(light=True).get("playing")
        with self._lock:
            kit = self.kit
        for cc, value in moved.items():
            d = cc_describe(cc)
            if d is None:
                continue
            inst, param = d
            if inst is None:
                changes.append({"cc": cc, "name": param, "value": value})
                # a master knob the user turned
                CHANGELOG.add("user", param.replace("_", " "),
                              detail=str(value), coalesce_key=f"master.{param}")
                continue
            kv = to_kit_value(param, value)
            if kit and inst in kit.get("instruments", {}):
                kit["instruments"][inst][param] = kv
            changes.append({"cc": cc, "instrument": inst, "param": param,
                            "value": value, "kit_value": kv})
            # LEVEL while playing is the sequencer's per-step accent, not a
            # human touch -- do not log it. A LEVEL move while stopped is the
            # fader; a knob (tune/decay/ctrl) is always the user.
            if param == "level" and playing:
                continue
            shown = (f"{param.upper()} -> {kv:+d}" if param == "tune"
                     else f"{param.upper()} {kv}")
            CHANGELOG.add("user", "fader" if param == "level" else "knob",
                          instrument=inst, detail=shown,
                          coalesce_key=f"{inst}.{param}")
        if changes:
            self.hub.publish({"type": "control", "changes": changes})

    def _on_transport(self, snap: dict):
        self._last_step = snap.get("step")
        moved = snap.get("controls") or {}
        if moved:
            self._on_control(moved)
        active = []
        with self._lock:
            pat = self.pattern
        if pat and pat.get("variations"):
            var = pat.get("view_variation") or next(iter(pat["variations"]), None)
            if var:
                active = active_instruments(pat["variations"].get(var, {}),
                                            snap.get("step", 0))
        self.hub.publish({"type": "transport", **snap, "active": active})

        # The machine announces neither the pattern nor the variation, so both
        # are recognised from what it plays. Matching is set arithmetic over
        # the fingerprint index; it runs on the MIDI thread, so a few times a
        # second rather than a few dozen.
        now = time.monotonic()
        if (self.follow_variation and snap.get("playing")
                and now - self._last_guess > 0.6):
            self._last_guess = now
            self._defer(self._recognise_now)

        if (self.focus_by_ear and snap.get("playing")
                and now - self._last_ear_check > 0.5):
            self._last_ear_check = now
            self._defer(self._focus_by_ear)

        # Panel step edits made while playing: heard, not read. Own cadence so
        # it keeps working even when variation-follow is off. Cheap -- a set
        # diff over what has sounded -- and only publishes when it finds a change.
        if (self.live_by_ear and snap.get("playing")
                and now - self._last_live_check > 0.5):
            self._last_live_check = now
            try:
                self._detect_live_edits()
            except Exception:
                pass

        # The TR-8S sends Program Change when a pattern is selected on the
        # panel. Reading the new pattern takes ~0.6s over SysEx, and this runs
        # on the MIDI reader thread -- doing it here would stall the clock. So
        # just record what is wanted and let the follower thread catch up;
        # rapid turns of the dial coalesce into one read of wherever it landed.
        pc = snap.get("pattern")
        if pc is None:
            return
        # A Program Change is an event, not a state. The monitor keeps the
        # last one it saw and this runs on every step tick, so act on each
        # arrival exactly once -- otherwise a pattern chosen in the studio was
        # dragged back to the machine's last announcement sixteen times a bar,
        # and a follow that could not complete was retried on every tick.
        at = snap.get("pattern_at")
        if at is not None:
            if at <= self._pc_handled:
                return
            self._pc_handled = at
        self.seen_program_change = True
        ch = snap.get("pattern_channel")
        if not self.follow:
            return

        if self.pattern_channel is None:
            full = self.monitor.snapshot()
            seen = full.get("program_channels") or []
            if len(seen) > 1:
                # Two channels are talking: the pattern on `Pattern Ch` and its
                # kit on `Kit Ch`, both a bare 0-127. Hand the burst to the
                # follower to work out which is which by reading.
                self._pending = list(full.get("recent_programs") or ())
                self._follow_wake.set()
                return
            # only one channel has ever spoken, so there is nothing to resolve

        if self.pattern_channel is not None and ch != self.pattern_channel:
            return                      # that was the kit channel, not ours
        if pc == self.slot:
            return
        self._want_slot = pc
        self._follow_wake.set()

    def _recognise_now(self):
        # the heavy buffers are fetched here, once, not on every step.
        # Only the last few seconds count: the buffer holds 256 hits, and
        # stale ones from before a variation change would outvote the new
        # ones for a whole bar. With the beat counter (CC 2) anchoring the
        # step, one bar of evidence is exactly aligned to the pattern; a
        # shorter window means a variation change is seen within a bar.
        hits = self.monitor.snapshot().get("hits") or []
        cutoff = time.monotonic() - 2.6
        self._recognise([h for h in hits if h[0] > cutoff])

    def _defer(self, job):
        """Run `job` on the listener thread -- or inline if none is running
        (tests, and the offline studio)."""
        if self._listener is None:
            try:
                job()
            except Exception:
                pass
            return
        if job not in self._listen_jobs:
            self._listen_jobs.append(job)
        self._listen_wake.set()

    def start_listener(self):
        """The thread that listens: variation recognition, TRACK by ear."""
        def run():
            while True:
                self._listen_wake.wait()
                self._listen_wake.clear()
                jobs, self._listen_jobs = self._listen_jobs, []
                for job in jobs:
                    try:
                        job()
                    except Exception:
                        pass
        if self._listener is None:
            self._listener = threading.Thread(target=run, daemon=True,
                                              name="tr8s-listen")
            self._listener.start()

    def start_follower(self):
        """Keep the view on whatever pattern the machine is actually on."""
        def run():
            while True:
                self._follow_wake.wait()
                self._follow_wake.clear()
                # let a spin of the dial settle before spending a read on it
                time.sleep(0.25)
                if self.pattern_channel is None:
                    self._learn_channel()
                while True:
                    want = self._want_slot
                    if want is None or want == self.slot:
                        break
                    self._want_slot = None
                    try:
                        self.select(want)
                        self._remember_slot(want)
                        self.hub.publish({"type": "followed", "slot": want,
                                          "panel": slot_to_panel(want)})
                    except DeviceError as e:
                        if "while the machine is playing" in str(e):
                            # cannot read now; show what we already know and
                            # let the syncer do a real read once it stops.
                            # Knowing nothing is no reason to stay behind:
                            # the machine IS on that pattern, so the studio
                            # goes there too, with an empty view until the
                            # first read.
                            if self._select_from_cache(want):
                                self.hub.publish({"type": "followed",
                                                  "slot": want,
                                                  "panel": slot_to_panel(want),
                                                  "from_cache": True})
                            else:
                                self._select_placeholder(want)
                                self.hub.publish({"type": "followed",
                                                  "slot": want,
                                                  "panel": slot_to_panel(want),
                                                  "placeholder": True})
                            self._want_resync = want
                            self._remember_slot(want)
                            break
                        self.hub.publish({"type": "log", "level": "err",
                                          "message": f"could not follow to "
                                                     f"{slot_to_panel(want)}: {e}"})
                        break
                    except Exception as e:
                        self.hub.publish({"type": "log", "level": "err",
                                          "message": f"could not follow to "
                                                     f"{slot_to_panel(want)}: {e}"})
                        break
        if self._follower is None:
            self._follower = threading.Thread(target=run, daemon=True,
                                              name="tr8s-follow")
            self._follower.start()

    def _select_from_cache(self, slot: int) -> bool:
        """
        Put a pattern on screen without touching the device.

        Used while the machine plays, when a read would hang. The device layer
        keeps the bytes of everything it has read or written; failing that,
        the fingerprint index knows every variation's steps, which is enough
        for the grid and for recognition even without name, tempo or kit.
        """
        dev = tool_device()
        blob = dev._blobs.get(("pattern", slot))
        if blob:
            p = Pattern.from_bytes(blob)
            d = p.describe()
            d.update(slot=slot, panel=slot_to_panel(slot))
            with self._lock:
                self.slot = slot
                self.pattern_obj = p
                d["melodies"] = self._melodies(p, self.kit)
                self.pattern = d
            self.hub.publish({"type": "pattern", "pattern": d,
                              "history": self._history()})
            return True
        entry = self.prints.entries.get(slot)
        if not entry:
            return False
        variations = {}
        for v, fp in entry["prints"].items():
            rows = {}
            for step, inst in fp:
                rows.setdefault(inst, ["."] * 16)[step] = "x"
            variations[v] = {k: "".join(r) for k, r in rows.items()}
        d = {"name": entry["name"], "slot": slot, "panel": slot_to_panel(slot),
             "variations": variations, "melodies": {}, "from_index": True,
             "tempo": None, "kit": None, "kit_panel": None}
        with self._lock:
            self.slot = slot
            self.pattern_obj = None
            self.pattern = d
        self.hub.publish({"type": "pattern", "pattern": d,
                          "history": self._history()})
        return True

    def simulate_panel_edit(self, variation: str, instrument: str,
                            index: int, value: str = "x") -> dict:
        """
        Diagnostic: change one step ON THE MACHINE without telling the studio.

        That is exactly what a hand on the panel does -- the slot changes and
        no MIDI says so -- and it is the only way to exercise panel-edit
        detection without a human. Every normal write path calls
        `dev.remember`, which is precisely what must not happen here.
        """
        dev = tool_device()
        slot = self.slot
        if slot is None:
            raise ToolError("no pattern is loaded")
        blob = dev._blobs.get(("pattern", slot))
        if blob is None:
            blob = dev.read_pattern(slot).to_bytes()     # refuses if playing
        p = Pattern.from_bytes(blob)
        row = p.variation_summary(variation).get(instrument, "")
        row = row.ljust(16, ".")
        index = max(0, min(15, int(index)))
        steps = row[:index] + value + row[index + 1:]
        p.set_steps(variation, instrument, steps)
        if not dev.transport.send_blob("pattern", slot, p.to_bytes()):
            raise ToolError("the machine did not accept the write")
        return {"slot": slot, "panel": slot_to_panel(slot),
                "variation": variation, "instrument": instrument,
                "index": index, "was": row, "now": steps,
                "note": "written to the machine only; the studio should pick "
                        "it up by itself within a few seconds (stopped)"}

    def _remember_slot(self, slot: int):
        """The machine is on this slot: remember it, so a restart resumes
        here instead of on a hard-coded pattern the machine is not on."""
        try:
            config.save_settings({"last_slot": int(slot)})
        except Exception:
            pass

    def _select_placeholder(self, slot: int) -> bool:
        """
        Move the studio onto a slot it knows nothing about.

        Used when the machine moves to a pattern while playing and there are
        neither cached bytes nor a fingerprint for it (an empty pattern about
        to be built, or one the index never managed to read). The view is
        empty, but the studio now agrees with the machine about *which*
        pattern is current, so the read on stop lands on the right slot and
        reports what was built there.
        """
        d = {"name": "", "slot": slot, "panel": slot_to_panel(slot),
             "variations": {}, "melodies": {}, "from_index": True,
             "placeholder": True, "tempo": None, "kit": None,
             "kit_panel": None}
        with self._lock:
            self.slot = slot
            self.pattern_obj = None
            self.pattern = d
        self.heard_variation = None
        self.hub.publish({"type": "pattern", "pattern": d,
                          "history": self._history()})
        return True

    def select(self, slot) -> dict:
        slot = slot if isinstance(slot, int) else int(slot)
        dev = tool_device()
        # A bulk read hangs during playback. If we already hold this pattern's
        # bytes (from before it started, or the fingerprint index), show those
        # and let the after-stop reader refresh -- never raise into the caller,
        # which is usually a tool-result refresh the user did not ask for.
        if self.monitor.snapshot(light=True).get("playing"):
            cached = dev._blobs.get(("pattern", slot))
            if cached is not None:
                return self._select_bytes(slot, cached)
            if self._select_from_cache(slot):
                self._want_resync = slot
                return self.pattern or {"slot": slot, "panel": slot_to_panel(slot)}
        p = dev.read_pattern(slot)
        d = p.describe()
        d.update(slot=slot, panel=slot_to_panel(int(slot)))
        kit = None
        try:
            kit = tool_call("kit.get", {"slot": p.kit})
            kit["_slot"] = p.kit
        except Exception:
            pass          # a pattern is still usable without its kit resolved
        d["melodies"] = self._melodies(p, kit)
        with self._lock:
            self.slot = slot
            self.pattern = d
            self.pattern_obj = p
            self.kit = kit
        self._remember_slot(slot)
        self.hub.publish({"type": "pattern", "pattern": d, "kit": kit})
        return d

    def _select_bytes(self, slot: int, blob: bytes) -> dict:
        """Build and publish a pattern view from bytes already held."""
        p = Pattern.from_bytes(blob)
        d = p.describe()
        d.update(slot=slot, panel=slot_to_panel(slot))
        kit = self.kit
        if kit is None or kit.get("_slot") != p.kit:
            try:
                kit = tool_call("kit.get", {"slot": p.kit})
                kit["_slot"] = p.kit
            except Exception:
                kit = self.kit
        d["melodies"] = self._melodies(p, kit)
        with self._lock:
            self.slot = slot
            self.pattern = d
            self.pattern_obj = p
            self.kit = kit
        self.hub.publish({"type": "pattern", "pattern": d, "kit": kit})
        return d

    def build_index(self, lo: int = 0, hi: int = 127):
        """
        Read every pattern's header into a browsable index, in the background.

        One pattern read is ~0.6s, so doing this on demand would stall the UI
        for over a minute. Progress is published as it goes, so the browser can
        fill in while it works.
        """
        def run():
            self.index_state = "building"
            for slot in range(lo, hi + 1):
                try:
                    p = tool_device().read_pattern(slot)
                except Exception:
                    continue
                entry = {"slot": slot, "panel": slot_to_panel(slot),
                         "name": p.name, "tempo": p.tempo, "kit": p.kit,
                         "variations": sorted(p.describe()["variations"])}
                with self._lock:
                    self.index[slot] = entry
                if slot % 8 == 0 or slot == hi:
                    self.hub.publish({"type": "index", "entries": [entry],
                                      "done": slot - lo + 1, "total": hi - lo + 1})
                else:
                    self.hub.publish({"type": "index", "entries": [entry]})
            self.index_state = "ready"
            self.hub.publish({"type": "index", "entries": [], "state": "ready"})

        if self.index_state == "building":
            return
        threading.Thread(target=run, daemon=True, name="tr8s-index").start()

    @staticmethod
    def _melodies(p, kit) -> dict:
        """
        Note names for any instrument carrying tune motion, per variation.

        Needs the tone's measured root -- Coarse Tune is relative to it -- so
        instruments whose tone is not in the catalogue are skipped rather than
        shown at a guessed pitch.

        Each entry carries `assumed`: true when the notes come from the CTRL
        byte, which only holds Coarse Tune if that is what is assigned to the
        instrument's CTRL knob. Nothing here can check that, so the view says
        so rather than presenting a pan sweep as a tune.
        """
        out: dict[str, dict[str, str]] = {}
        insts = (kit or {}).get("instruments", {})
        for v in VARIATIONS:
            tracks = p.variation_summary(v)
            for inst in tracks:
                root = (insts.get(inst) or {}).get("root")
                if not root:
                    continue
                motion = [p.get_motion(v, inst, s) for s in range(16)]
                if not any(m["mask"] for m in motion):
                    continue
                mode = "coarse" if any(m["ctrl"] is not None for m in motion) else "fine"
                try:
                    notes = melodymod.read(p, v, inst, root, mode=mode)
                except Exception:
                    continue
                out.setdefault(v, {})[inst] = {
                    "notes": notes, "mode": mode, "root": root,
                    "assumed": mode == "coarse",
                }
        return out

    @staticmethod
    def _history() -> dict:
        from .history import HISTORY
        return {"undo": len(HISTORY), "redo": len(HISTORY.redo_entries(64))}

    def state(self) -> dict:
        with self._lock:
            pat, kit = self.pattern, self.kit
        with self._lock:
            index = sorted(self.index.values(), key=lambda e: e["slot"])
        return {
            "kit": kit,
            "index": index,
            "index_state": self.index_state,
            "connected": self.connected,
            "info": self.info,
            "transport": self.monitor.snapshot(light=True),
            "slot": self.slot,
            "pattern": pat,
            "instruments": TRACKS,
            "variations": list(VARIATIONS),
            "chat": self.chat_status(),
            "history": self._history(),
            "variation": {"follow": self.follow_variation,
                          "heard": self.heard_variation,
                          "heard_slot": self.heard_slot},
            "prints": {"state": self.prints_state, "have": len(self.prints)},
            "focus_by_ear": self.focus_by_ear,
            "follow": {"on": self.follow,
                       "seen_program_change": self.seen_program_change,
                       "channel": self.pattern_channel,
                       "kit_channel": self.kit_channel,
                       "channels_seen": (self.monitor.snapshot()
                                         .get("program_channels") or [])},
        }

    def _editable_pattern(self):
        """
        Return (pattern_obj, slot) ready to edit, upgrading an index-only view.

        The grid can be showing a pattern built from the fingerprint index
        (steps only, no real bytes) -- that happens whenever a slot was
        selected while the machine played. Such a view has no live Pattern to
        mutate, so an edit would fail with "no pattern is loaded" even though
        one is plainly on screen. Recover the real bytes: read them if the
        machine is stopped, or use a cached blob if we hold one. We never
        reconstruct a Pattern from index steps and write it back -- that would
        wipe accents and the kit reference.
        """
        with self._lock:
            p, slot = self.pattern_obj, self.slot
        if p is not None or slot is None:
            return p, slot
        playing = bool(self.monitor.snapshot(light=True).get("playing"))
        if not playing:
            try:
                self.select(slot)
            except Exception:
                pass
        else:
            blob = tool_device()._blobs.get(("pattern", slot))
            if blob is not None:
                try:
                    self._select_bytes(slot, blob)
                except Exception:
                    pass
        with self._lock:
            return self.pattern_obj, self.slot

    def step_edit(self, variation: str, instrument: str, index: int,
                  value: str) -> dict:
        """
        Toggle one step on the cached pattern and push it to the edit buffer.

        Skips re-reading the pattern from the device, which is what made
        click-to-edit feel sluggish -- a read is ~0.6s on top of the write.
        """
        p, slot = self._editable_pattern()
        if slot is None:
            raise DeviceError("no pattern is loaded; select one first")
        if p is None:
            raise DeviceError("the machine is playing and this pattern was "
                              "never read while stopped -- stop briefly to edit")
        self._refuse_stale_write()
        if value not in ".oxX":
            raise ToolError(f"step value must be one of . o x X, got {value!r}")
        if not 0 <= index < 16:
            raise ToolError(f"step index {index} out of range 0..15")
        dev = tool_device()
        self.busy = True
        # snapshot before touching the cached Pattern: these edits do not go
        # through tools.call, so nothing else would record them
        HISTORY.capture(dev, "pattern", slot,
                        f"{instrument} step {index + 1} -> {value}")
        cur = p.get_steps(variation, instrument)
        steps = cur[:index] + value + cur[index + 1:]
        p.set_steps(variation, instrument, steps)
        if not dev.transport.send_blob("pattern", slot, p.to_bytes()):
            raise DeviceError("transfer incomplete")
        dev.remember("pattern", slot, p.to_bytes())
        d = p.describe()
        d.update(slot=slot, panel=slot_to_panel(slot))
        with self._lock:
            d["melodies"] = self._melodies(p, self.kit)
            self.pattern = d
        self.busy = False
        CHANGELOG.add("studio", "step", instrument=instrument,
                      detail=f"step {index + 1} = {value}", slot=slot)
        self.hub.publish({"type": "pattern", "pattern": d,
                          "history": self._history(),
                          "changed": [instrument]})
        return {"steps": steps, "variation": variation,
                "instrument": instrument, "committed": False, "live": True}

    def note_edit(self, variation: str, instrument: str, index: int,
                  note: str | None, root: str) -> dict:
        """
        Set one step's pitch, without rewriting the rest of the line.

        This is the whole point of the studio: on the machine itself, changing
        one note of a melody means holding a button and turning a knob while
        reading a two-line display. Here it is one keystroke.

        `note` of None clears the step to a rest, motion and all.
        """
        p, slot = self._editable_pattern()
        self._refuse_stale_write()
        if slot is None:
            raise DeviceError("no pattern is loaded; select one first")
        if p is None:
            raise DeviceError("the machine is playing and this pattern was "
                              "never read while stopped -- stop briefly to edit")
        if not 0 <= index < 16:
            raise ToolError(f"step index {index} out of range 0..15")

        # a bad note is the caller's mistake, not a server fault: turn the
        # model's error into one the HTTP layer reports as a 400
        try:
            root_midi = melodymod.note_to_midi(root)
            midi = None if note is None else melodymod.note_to_midi(note)
        except melodymod.MelodyError as e:
            raise ToolError(str(e)) from None
        if root_midi is None:
            raise ToolError("root must be a real note, e.g. C2")

        dev = tool_device()
        self.busy = True
        HISTORY.capture(dev, "pattern", slot,
                        f"{instrument} step {index + 1} -> {note or 'rest'}")
        cur = p.get_steps(variation, instrument)
        if note is None:
            p.clear_motion(variation, instrument, index)
            steps = cur[:index] + "." + cur[index + 1:]
        else:
            if midi is None:
                raise ToolError("note must be a real note, or null for a rest")
            semis = midi - root_midi
            if not melodymod.COARSE_MIN <= semis <= melodymod.COARSE_MAX:
                raise ToolError(
                    f"{note} is {semis:+d} semitones from {root}, outside "
                    f"Coarse Tune's {melodymod.COARSE_MIN}.."
                    f"{melodymod.COARSE_MAX}")
            p.set_motion(variation, instrument, index,
                         ctrl=semis + melodymod.COARSE_OFFSET)
            # a step with no hit makes no sound to bend, so give it one
            steps = cur[:index] + (cur[index] if cur[index] != "." else "x") \
                + cur[index + 1:]
        p.set_steps(variation, instrument, steps)

        if not dev.transport.send_blob("pattern", slot, p.to_bytes()):
            raise DeviceError("transfer incomplete")
        dev.remember("pattern", slot, p.to_bytes())
        d = p.describe()
        d.update(slot=slot, panel=slot_to_panel(slot))
        with self._lock:
            d["melodies"] = self._melodies(p, self.kit)
            self.pattern = d
        self.busy = False
        CHANGELOG.add("studio", "note", instrument=instrument,
                      detail=f"step {index + 1} = {note or 'rest'}", slot=slot)
        self.hub.publish({"type": "pattern", "pattern": d,
                          "history": self._history(),
                          "changed": [instrument]})
        return {"note": note, "steps": steps, "variation": variation,
                "instrument": instrument, "committed": False, "live": True}

    # --------------------------------------------------------------- chat

    def init_chat(self):
        """
        Pick the assistant backend. Claude Code (the user's own sign-in, a
        Pro/Max subscription) is preferred; the plain API with a key is the
        fallback. Neither being ready is not an error -- the UI shows how to
        connect one.
        """
        self.chat = None
        self.chat_error = None
        self.chat_backend = None
        sdk_ok, sdk_why = agentmod.sdk_available()
        if sdk_ok:
            self.chat_backend = "claude-code"
            ok, why = agentmod.available()
            if ok:
                try:
                    saved = config.load_settings()
                    # the conversation survives a studio restart: the SDK
                    # keeps sessions on disk, so pick up where it left off
                    self.chat = agentmod.Agent(
                        model=saved.get("chat_model") or agentmod.DEFAULT_MODEL,
                        context=self.chat_context,
                        resume=saved.get("chat_session"))
                    agentmod.on_machine_moved = self._machine_moved_by_tool
                except Exception as e:
                    self.chat_error = str(e)
            else:
                self.chat_error = why
            return
        from . import chat as chatmod
        ok, why = chatmod.available()
        if not ok:
            self.chat_error = f"{sdk_why}; {why}"
            return
        try:
            self.chat = chatmod.Chat()
            self.chat_backend = "api"
        except Exception as e:
            self.chat_error = str(e)

    def _machine_moved_by_tool(self, slot: int):
        """The assistant moved the machine (device.select): follow it."""
        if slot == self.slot:
            return
        try:
            self.select(slot)
        except Exception:
            self._select_from_cache(slot) or self._select_placeholder(slot)
            self._want_resync = slot
        self.hub.publish({"type": "followed", "slot": slot,
                          "panel": slot_to_panel(slot), "by": "assistant"})

    def chat_context(self) -> str:
        """What the studio sees, for the assistant: the machine's pattern,
        transport, and the recent changes -- the memory a collaborator needs."""
        with self._lock:
            pat = dict(self.pattern or {})
            kit = self.kit
        snap = self.monitor.snapshot(light=True)
        lines = []
        if pat.get("slot") is not None:
            name = pat.get("name") or "(not read yet)"
            lines.append(f"pattern on screen (the machine's): {pat.get('panel')} "
                         f"\"{name}\" (slot {pat.get('slot')}), tempo "
                         f"{pat.get('tempo')}, kit {pat.get('kit_panel')}"
                         + (f" \"{kit.get('name')}\"" if kit and kit.get('name') else ""))
            used = {v: sorted(rows) for v, rows in (pat.get("variations") or {}).items()
                    if rows}
            if used:
                lines.append("variations with steps: " + ", ".join(
                    f"{v}({','.join(insts)})" for v, insts in used.items()))
            else:
                lines.append("variations with steps: none (empty pattern)")
        else:
            lines.append("no pattern on screen yet")
        lines.append("machine: " + ("PLAYING" if snap.get("playing") else "stopped")
                     + (f" at {snap.get('bpm')} BPM" if snap.get("bpm") else "")
                     + (f", variation {self.heard_variation} heard"
                        if self.heard_variation else ""))
        try:
            recent = [e for e in CHANGELOG.recent(40)
                      if e.get("action") in ("steps", "select", "knob", "tone",
                                             "set instrument", "generate",
                                             "arrange", "create", "swap")]
            recent = recent[-10:]
            if recent:
                lines.append("recent changes (oldest first): " + "; ".join(
                    f"{e['source']} {e['action']}"
                    + (f" {e['instrument']}" if e.get("instrument") else "")
                    + (f": {e['detail']}" if e.get("detail") else "")
                    for e in recent))
        except Exception:
            pass
        return "\n".join(lines)

    def chat_status(self) -> dict:
        st = {"available": self.chat is not None,
              "reason": self.chat_error,
              "backend": self.chat_backend,
              "sdk": agentmod.sdk_available()[0],
              "auth": agentmod.auth_status(),
              "login_in_progress": self._login is not None,
              "login_url": getattr(self._login, "url", None),
              "models": list(agentmod.MODELS),
              "auth_mode": agentmod.auth_mode(),
              "has_key": bool(agentmod.api_key()),
              "key_hint": (lambda k: (k[:10] + "…" + k[-4:]) if k else None)(
                  agentmod.api_key())}
        if self.chat is not None and hasattr(self.chat, "status"):
            st.update(self.chat.status())
        return st

    def ask(self, message: str) -> dict:
        if self.chat is None:
            # maybe the user signed in since start
            self.init_chat()
        if self.chat is None:
            return {"error": self.chat_error or "no assistant is connected"}
        def emit(ev):
            # wrapped, not merged: the inner event has a "type" of its own
            self.hub.publish({"type": "chat", "event": ev})
        reply = self.chat.send(message, emit=emit)
        sid = getattr(self.chat, "session_id", None)
        if sid:
            config.save_settings({"chat_session": sid})
        # the model may have changed the pattern; refresh the cached view
        if self.slot is not None:
            try:
                self.select(self.slot)
            except Exception:
                pass
        return {"reply": reply}

    def chat_stop(self) -> dict:
        if self.chat is not None and hasattr(self.chat, "interrupt"):
            self.chat.interrupt()
        return self.chat_status()

    def chat_reset(self) -> dict:
        if self.chat is not None:
            self.chat.reset()
        config.save_settings({"chat_session": None})
        self.hub.publish({"type": "chat", "event": {"type": "reset"}})
        return self.chat_status()

    def chat_model(self, model: str) -> dict:
        if self.chat is not None and hasattr(self.chat, "set_model"):
            self.chat.set_model(model)
        config.save_settings({"chat_model": model})
        return self.chat_status()

    def login(self, console: bool = False) -> dict:
        """Start the browser sign-in; progress arrives as `auth` events."""
        if self._login is not None:
            return self.chat_status()

        def on_line(text, url):
            self.hub.publish({"type": "auth", "stage": "line", "text": text,
                              "url": url})

        def on_done(status):
            self._login = None
            self.hub.publish({"type": "auth", "stage": "done",
                              "status": status})
            self.init_chat()
            self.hub.publish({"type": "chat", "event": {
                "type": "status", "status": self.chat_status()}})

        self._login = agentmod.Login(on_line, on_done, console=console)
        try:
            self._login.start()
        except Exception as e:
            self._login = None
            raise ToolError(str(e))
        self.hub.publish({"type": "auth", "stage": "started"})
        return self.chat_status()

    def login_cancel(self) -> dict:
        if self._login is not None:
            self._login.cancel()
        return self.chat_status()

    def logout(self) -> dict:
        if self.chat is not None:
            try:
                self.chat.reset()
            except Exception:
                pass
        status = agentmod.logout()
        self.init_chat()
        self.hub.publish({"type": "auth", "stage": "done", "status": status})
        return self.chat_status()


STUDIO = Studio()



def _log_tool_change(source: str, name: str, args: dict, result):
    """Record a mutating tool call in the change log, tagged by who ran it."""
    spec = REGISTRY.get(name)
    if not spec or not spec.get("mutates_device"):
        return
    inst = args.get("instrument") or args.get("assign_to")
    slot = args.get("slot")
    short = name.split(".")[-1].replace("_", " ")
    detail = ""
    if name == "kit.set_instrument" and "tone" in args:
        chosen = (result or {}).get("instrument", {})
        detail = f"tone {args['tone']}" + (f" ({chosen.get('tone_name')})"
                                           if chosen.get("tone_name") else "")
    elif name in ("kit.swap",) and isinstance(result, dict):
        c = result.get("chosen") or {}
        detail = c.get("name", args.get("description", ""))
    elif name in ("sample.import", "sample.fetch") and isinstance(result, dict):
        inst = args.get("assign_to")
        detail = f"{result.get('name')} (tone {result.get('tone')})"
    elif name == "pattern.set_line":
        detail = f"{args.get('shape', '')} line {args.get('key', '')}".strip()
    elif name in ("pattern.set_steps", "pattern.set_note"):
        detail = str(args.get("steps") or args.get("note") or "")
    elif name == "kit.tune_to":
        detail = f"-> {args.get('note')}"
    try:
        CHANGELOG.add(source, short, instrument=inst, detail=detail,
                      slot=int(slot) if isinstance(slot, int) else None)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "tr8s-studio"

    def log_message(self, fmt, *args):
        pass          # quiet; errors are reported explicitly

    # ----------------------------------------------------------- helpers

    def _send(self, code: int, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def _upload(self):
                # a WAV dropped or picked in the browser. The body is the raw
            # file; the query string names it and says where it goes.
            from urllib.parse import parse_qs, urlparse
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b""
            if not data.startswith(b"RIFF"):
                return self._json({"error": "not a WAV file"}, 400)
            dest_dir = config.data_dir() / "samples"
            dest_dir.mkdir(parents=True, exist_ok=True)
            fname = re.sub(r"[^A-Za-z0-9._-]", "_", q.get("name") or "upload")
            if not fname.lower().endswith(".wav"):
                fname += ".wav"
            dest = dest_dir / fname
            dest.write_bytes(data)
            args = {"path": str(dest), "name": (q.get("name") or fname)[:16]}
            if q.get("assign_to"):
                args["assign_to"] = q["assign_to"]
                args["slot"] = STUDIO.pattern["kit"] if STUDIO.pattern else None
            if q.get("reuse_tone"):
                args["reuse_tone"] = int(q["reuse_tone"])
            try:
                result = tool_call("sample.import", args)
            except ToolError as e:
                return self._json({"error": str(e)}, 400)
            if STUDIO.slot is not None:
                try:
                    STUDIO.select(STUDIO.slot)
                except Exception:
                    pass
            return self._json({"result": result})


    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as e:
            raise ToolError(f"invalid JSON body: {e}")

    def _static(self, name: str):
        path = (WEB / name).resolve()
        if not str(path).startswith(str(WEB.resolve())) or not path.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = {"html": "text/html; charset=utf-8",
                 "css": "text/css; charset=utf-8",
                 "js": "application/javascript; charset=utf-8",
                 "svg": "image/svg+xml"}.get(path.suffix.lstrip("."), "text/plain")
        self._send(200, path.read_bytes(), ctype)

    # --------------------------------------------------------------- GET

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p in ("/", "/index.html"):
                return self._static("index.html")
            if p.startswith("/static/"):
                return self._static(p[len("/static/"):])
            if p == "/api/state":
                return self._json(STUDIO.state())
            if p == "/api/tools":
                return self._json(schemas())
            if p == "/api/events":
                return self._events()
            self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _events(self):
        q = STUDIO.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self._push({"type": "hello", **STUDIO.state()})
            while True:
                try:
                    ev = q.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self._push(ev)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            STUDIO.hub.unsubscribe(q)

    def _push(self, ev: dict):
        payload = json.dumps(ev, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode())
        self.wfile.flush()

    # -------------------------------------------------------------- POST

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/upload":
                # raw bytes, not JSON: handled before _body() would try to parse it
                return self._upload()
            body = self._body()
            if p == "/api/tool":
                name = body.get("name")
                args = body.get("args") or {}
                if not name:
                    return self._json({"error": "missing 'name'"}, 400)
                try:
                    result = tool_call(name, args)
                except ToolError as e:
                    return self._json({"error": str(e)}, 400)
                _log_tool_change("studio", name, args, result)
                # a write may have changed what is on screen. A kit write
                # changes the strips and the SOUND bar; without this the view
                # kept showing the old tone after an audition had already put
                # a new one on the machine.
                if (name.startswith(("pattern.", "kit.", "track.", "library."))
                        and STUDIO.slot is not None
                        and REGISTRY[name].get("mutates_device")):
                    try:
                        STUDIO.select(STUDIO.slot)
                    except Exception:
                        pass
                return self._json({"result": result})

            if p == "/api/step":
                return self._json(STUDIO.step_edit(
                    body.get("variation", "A"), body.get("instrument", "BD"),
                    int(body.get("index", 0)), body.get("value", ".")))

            if p == "/api/note":
                return self._json(STUDIO.note_edit(
                    body.get("variation", "A"), body.get("instrument", "LT"),
                    int(body.get("index", 0)), body.get("note"),
                    body.get("root") or "C2"))

            if p == "/api/inject":
                # feed raw MIDI bytes into the studio's own monitor, exactly
                # as if the machine had sent them. Diagnostic: it is how the
                # knob-follow path was proven without a hand on the panel.
                raw = bytes.fromhex(body.get("hex", ""))
                if not raw:
                    return self._json({"error": "give hex bytes"}, 400)
                STUDIO.midilog.feed(raw)
                if raw[0] >= 0xF8:
                    STUDIO.monitor.feed(raw)
                else:
                    STUDIO.monitor.feed_channel(raw)
                return self._json({"injected": raw.hex(" ")})

            if p == "/api/simulate_panel_edit":
                # diagnostic twin of /api/inject: a step edit the machine
                # made and the studio was not told about (see LESSONS.md,
                # "Testing without hands on the machine")
                return self._json(STUDIO.simulate_panel_edit(
                    body.get("variation", "A"), body.get("instrument", "BD"),
                    int(body.get("index", 0)), body.get("value", "x")))

            if p == "/api/changelog":
                if body.get("clear"):
                    CHANGELOG.clear()
                if "enabled" in body:
                    CHANGELOG.enabled = bool(body["enabled"])
                return self._json({
                    "entries": CHANGELOG.recent(int(body.get("limit", 150)),
                                                body.get("source")),
                    "enabled": CHANGELOG.enabled,
                    "count": len(CHANGELOG),
                    "text": CHANGELOG.as_text(int(body.get("limit", 200)))})

            if p == "/api/midilog":
                if body.get("clear"):
                    STUDIO.midilog.clear()
                if "clock" in body:
                    STUDIO.midilog.show_clock = bool(body["clock"])
                return self._json({
                    "entries": STUDIO.midilog.entries(int(body.get("limit", 120))),
                    "summary": STUDIO.midilog.summary(),
                    "clock": STUDIO.midilog.show_clock,
                    "text": STUDIO.midilog.as_text(
                        int(body.get("limit", 120)))})

            if p == "/api/fingerprints":
                STUDIO.build_fingerprints()
                return self._json({"state": STUDIO.prints_state,
                                   "have": len(STUDIO.prints)})

            if p == "/api/variation":
                if "follow" in body:
                    STUDIO.follow_variation = bool(body["follow"])
                return self._json(STUDIO.state()["variation"])

            if p == "/api/follow":
                if "on" in body:
                    STUDIO.follow = bool(body["on"])
                if "ear" in body:
                    STUDIO.focus_by_ear = bool(body["ear"])
                if "channel" in body:
                    ch = body["channel"]
                    STUDIO.pattern_channel = None if ch is None else int(ch)
                    config.save_settings(
                        {"pattern_channel": STUDIO.pattern_channel})
                return self._json(STUDIO.state()["follow"])

            if p == "/api/undo":
                from .history import HISTORY
                d = tool_device()
                try:
                    r = (HISTORY.redo(d) if body.get("redo")
                         else HISTORY.undo(d))
                except LookupError as e:
                    return self._json({"error": str(e)}, 400)
                # the cached pattern is now stale -- re-read so the UI agrees
                if STUDIO.slot is not None:
                    try:
                        STUDIO.select(STUDIO.slot)
                    except Exception:
                        pass
                return self._json(r)

            if p == "/api/commit":
                if STUDIO.slot is None:
                    return self._json({"error": "no pattern loaded"}, 400)
                tool_device().transport.commit("pattern", STUDIO.slot)
                return self._json({"committed": True, "slot": STUDIO.slot,
                                   "panel": slot_to_panel(STUDIO.slot)})

            if p == "/api/select":
                slot = body.get("slot")
                if slot is None:
                    return self._json({"error": "missing 'slot'"}, 400)
                from .tools import _slot
                return self._json({"pattern": STUDIO.select(_slot(slot))})

            if p == "/api/chat":
                msg = (body.get("message") or "").strip()
                if not msg:
                    return self._json({"error": "empty message"}, 400)
                return self._json(STUDIO.ask(msg))
            if p == "/api/chat/stop":
                return self._json(STUDIO.chat_stop())
            if p == "/api/chat/reset":
                return self._json(STUDIO.chat_reset())
            if p == "/api/chat/model":
                return self._json(STUDIO.chat_model(str(body.get("model"))))
            if p == "/api/chat/status":
                return self._json(STUDIO.chat_status())
            if p == "/api/auth/login":
                return self._json(STUDIO.login(bool(body.get("console"))))
            if p == "/api/auth/cancel":
                return self._json(STUDIO.login_cancel())
            if p == "/api/auth/logout":
                return self._json(STUDIO.logout())
            if p == "/api/auth/key":
                # paste (or clear) an API key; kept in the studio's own
                # settings file, mode 600, never shown back in full
                try:
                    agentmod.save_key(body.get("key"))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if body.get("key"):
                    agentmod.set_auth_mode("apikey")
                STUDIO.init_chat()
                return self._json(STUDIO.chat_status())
            if p == "/api/auth/key/test":
                return self._json(agentmod.test_key(body.get("key")))
            if p == "/api/auth/mode":
                try:
                    agentmod.set_auth_mode(str(body.get("mode")))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                STUDIO.init_chat()
                return self._json(STUDIO.chat_status())

            if p == "/api/index":
                STUDIO.build_index()
                return self._json({"state": STUDIO.index_state,
                                   "have": len(STUDIO.index)})

            if p == "/api/reconnect":
                ok = STUDIO.connect()
                return self._json({"connected": ok, "info": STUDIO.info})

            self._send(404, b"not found", "text/plain")
        except ToolError as e:
            self._json({"error": str(e)}, 400)
        except (TransportError, OSError) as e:
            # only a transport-level failure means the device actually went away
            STUDIO.mark_disconnected(e)
            self._json({"error": f"{e} (the device may have been unplugged; "
                                 f"reconnecting automatically)"}, 502)
        except DeviceError as e:
            # an ordinary failure -- a slot that would not read, say. The device
            # is still there, so do not raise a disconnection alarm.
            self._json({"error": str(e)}, 502)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="tr8s-studio")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--slot", default=None,
                    help="pattern to show on startup, e.g. 8-07")
    ap.add_argument("--offline", action="store_true",
                    help="run against an in-memory TR-8S, with no hardware")
    args = ap.parse_args(argv)

    if args.offline:
        from . import demo
        demo.install()
        if args.slot is None:
            args.slot = demo.default_slot()
        print("device: OFFLINE -- an in-memory TR-8S. Edits go nowhere real.",
              flush=True)

    ok = STUDIO.connect()
    # the watchdog exists to re-open a physical port; offline there is none
    if not args.offline:
        STUDIO.start_watchdog()
    STUDIO.start_follower()
    STUDIO.start_after_stop_reader()
    STUDIO.start_listener()
    CHANGELOG.bind(config.data_dir() / "session-changelog.jsonl")
    if not args.offline:
        print(f"device: {'connected ' + str(STUDIO.info) if ok else STUDIO.info}",
              flush=True)
    if not ok and not args.offline:
        print("        (watchdog will keep retrying; the UI still loads)",
              flush=True)
    STUDIO.init_chat()
    print(f"chat:   {'ready' if STUDIO.chat else STUDIO.chat_error}", flush=True)
    # Resume on the slot the machine was last seen on, unless told otherwise.
    # The machine cannot be asked which pattern it is on, and says nothing
    # until the dial moves; the last followed slot is the best guess there is.
    start_slot = args.slot
    if start_slot is None:
        start_slot = config.load_settings().get("last_slot")
    if ok and start_slot is not None:
        try:
            from .tools import _slot
            STUDIO.select(start_slot if isinstance(start_slot, int)
                          else _slot(start_slot))
            print(f"pattern: {STUDIO.pattern['name']} "
                  f"({slot_to_panel(STUDIO.slot)})", flush=True)
        except Exception as e:
            print(f"pattern: could not read {start_slot}: {e}", flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"\n  tr8s studio -> http://{args.host}:{args.port}\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        srv.server_close()
        tool_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
