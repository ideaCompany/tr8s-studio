# Handoff — start here for a new context

Written 2026-09-02. This is the single doc to read first when picking the
project up cold. It says what the thing is, where everything lives, what works,
the truths you must not relearn the hard way, and what to do next. Everything
here is verified against real hardware (TR-8S, firmware 2.51) unless marked.

## The goal

You can talk to a Roland TR-8S through an LLM and get great techno out of it —
"vibe chat to the machine and let it make music." Two surfaces on one backend:
a **chat** loop that calls named tools, and a **studio** web UI that mirrors and
drives the machine live. The machine is the source of truth; the studio follows
it and can also drive it.

## Where everything is

Repo root: `/home/svh/tr8s`

| Path | What it is |
|---|---|
| `src/tr8s/transport.py` | SysEx on the wire: framing, checksum, 7-bit packing, chunked read/write, the realtime/channel reader split. |
| `src/tr8s/device.py` | Connection facade + `panel_to_slot`/`slot_to_panel`. Owns the byte cache (`_blobs`). |
| `src/tr8s/pattern.py` `kit.py` `melody.py` `tones.py` | Pure models over blobs; testable with no hardware. |
| `src/tr8s/monitor.py` | Live MIDI monitor: clock/step/bar/BPM, heard notes (`live`), Program Change, CC. **`feed` = realtime, `feed_channel` = channel messages** (reassembles messages split by an interleaved clock). |
| `src/tr8s/fingerprint.py` | Pattern/variation recognition by `(step,inst)` set arithmetic over all 16 rotations. |
| `src/tr8s/changelog.py` | Tagged session log (`user`/`ai`/`studio`/`system`), coalesces knob sweeps, JSONL-persisted. |
| `src/tr8s/server.py` | The studio: HTTP + SSE, follow logic, live overlay, panel-edit detection, all `/api/*` routes. **The big one (~1500 lines).** |
| `src/tr8s/tools/` | The command surface (one decorator per tool + JSON schema). `_core.py` holds the registry. Package split by namespace: `pattern`, `kit`, `device`, `tones`, `library`, `lines`, `track`, `audio`, `calibration`, `history`. |
| `src/tr8s/agent.py` | **The assistant.** The chat on the Claude Agent SDK: drives the user's own `claude` sign-in (Pro/Max) or a pasted API key, serves the tool registry to the model as an in-process MCP server, streams prose + reasoning + tool calls to the UI, keeps one session (resumed across restarts), runs the browser sign-in. |
| `src/tr8s/chat.py` `mcp_server.py` | The plain-API tool-calling loop (needs a key; fallback when the SDK is absent) and the system prompt both backends share; the same registry over MCP (stdio). |
| `src/tr8s/web/{index.html,app.js,app.css}` | The UI. Vanilla JS/CSS, no build step, themed via CSS custom properties. Two views: step **grid** and machine **panel**. |
| `src/tr8s/style.py` `kitbuild.py` `swap.py` `samples.py` | Groove generation, kit assembly from the measured catalogue, sound swaps, WAV→tone import. |
| `docs/` | See below. |
| `tests/` | 490+ passing, 7 skipped. `tests/hardware/selftest.py` needs the machine and a free port. |
| `scripts/restart.sh` | Safe studio restart (see "Running" below). |

`README.md` is the front door (commercial, for the open-source release);
`docs/README-dev.md` is the older developer README (CLI, Python API);
`docs/UX-NOTES.md` lists rough edges seen while demoing — good first issues.
Screenshots for the README live in `docs/screenshots/`.

Docs, in reading order for depth: **HANDOFF.md** (this) → `ARCHITECTURE.md`
(layers, module map) → `PROTOCOL.md` (the reverse-engineered SysEx/MIDI wire
format, 40KB, authoritative) → `LESSONS.md` (every trap already hit, with the
fix — read before changing MIDI parsing, sample writing, or follow) → `PANEL.md`
(the machine's front panel, CC map) → `ROADMAP.md` (what's next) →
`EXPERIMENTS.md` / `OVERNIGHT.md` (log of unattended runs).

Persistent memory (survives across sessions):
`/home/svh/.claude/projects/-home-svh/memory/` — `tr8s-project.md`,
`tr8s-sysex.md`, `MEMORY.md` (index).

## Running

```bash
scripts/restart.sh --slot 8-16          # stop old by PID, wait for the port, start
# opens http://127.0.0.1:8733
python3 -m tr8s.cli tools               # every tool + JSON schema
python3 -m pytest tests/                # 490+ passed, 7 skipped (~60s)
```

MIDI port is auto-discovered under `/dev/snd/midiC*D*` (override `TR8S_PORT`).
Data dir is `$TR8S_DATA` else XDG. `--offline` runs the UI with no machine.

## What works (verified live this session)

- **Follow the machine's pattern.** Program Change (Tx Prog Chg on) moves the
  studio to whatever pattern is selected on the panel — while playing too,
  even onto a slot nothing is known about (placeholder view, read on stop).
  Each PC is acted on once; a pattern picked in the studio stays picked.
- **Follow the variation (A–H).** Recognised by ear from what's playing (set
  arithmetic over the fingerprint index), since the machine announces neither.
- **Live overlay.** Steps light in the grid/panel as they are heard, playing.
- **Knob/fader sync.** Panel knob and fader moves (Tx EditData on) move the
  on-screen controls and are logged; a knob *sweep* logs as one net line
  (`DECAY +20 → +45 (1.2s)`), not a hundred.
- **Panel step-edit detection.** The machine transmits nothing when a step is
  toggled. Stopped: caught by the ~1.6s poll (read back + diff, exact), logs
  `user`, brings TRACK to the instrument. Playing: TRACK follows the instrument
  whose *heard* part changed against its own previous bars (`focus_by_ear`,
  MIDI notes, not audio) within one to two bars, and the heard steps become
  the pattern on screen and a log entry right away; the exact read on stop
  reconciles silently. Verified with a hand on the panel 2026-09-02, on
  unsaved edits (no WRITE needed). A studio write over unread panel edits is
  refused while playing, with the reason.
- **Tempo readout** is steady to 0.1 BPM (robust clock-period estimate; the
  heavy listening work runs on its own thread so the MIDI reader never stalls).
- **Studio grid edits + chat/AI tool calls.** Both logged (`studio` / `ai`),
  both auto-focus the instrument. Writes hit the machine live.
- **Change log.** Toggleable, persisted, colour-coded by source. It is the
  memory an AI collaborator needs ("the user shortened the snare two bars ago").
- **Samples.** WAV→16-bit mono 44.1k import, fetch, drag-drop/click-click
  hotswap, all while playing. Kit colour read/write. Undo ring buffer.
- **The assistant, on a Claude subscription.** PROMPT panel: chip shows
  `CLAUDE · MAX · OPUS`; "connect an assistant" chooser (Claude sign-in via
  the browser, or an API key with steps + TEST + USE; other providers greyed
  out). Every turn carries a `[studio]` context block (the machine's pattern,
  transport, recent changes) so "this pattern" means the right thing. Verified
  2026-09-02: "create me a new techno track on 8-06" → read the slot, chose a
  safe kit, `track_create`, moved the machine there, reported seed + undo, in
  58s; follow-ups keep the session. Terms note in `agent.py`: subscription
  login is fine for personal use, not for distribution.

## Truths you must not relearn the hard way

These are in `LESSONS.md` in full; the load-bearing ones:

1. **Bulk SysEx reads HANG during playback (~25s).** Never read a pattern while
   playing. Writes succeed while playing (~1.4s) — that's why editing is live.
2. **The panel sends nothing for a step toggle or a variation select.** Steps
   are known only by reading back and diffing (stopped). Variation only by ear.
3. **Detecting *exact steps* by ear while playing is unreliable** and is OFF by
   default (`live_by_ear`). Rolls, sub-steps, pitched voices and swing make the
   heard grid diverge from the stored grid (measured: ~10 false adds / 15s on a
   ROLLERS pattern). Trust the read-back, which is exact. What *does* work by
   ear is heard-vs-heard: which instrument's part changed against its own
   previous bars (`focus_by_ear`, ON) — enough to move TRACK, never logged as
   steps.
4. **MIDI realtime bytes interleave anywhere, even mid-message.** A clock byte
   between a Program Change's status and value split it across reader payloads
   and killed follow-while-playing. `feed_channel` now reassembles across calls.
   If you touch the reader or the monitor parse, keep this.
5. **`/api/select` (studio) only changes the *display*; `device.select` (tool)
   drives the *machine*.** They can point at different patterns — a desync that
   makes any heard-vs-stored comparison meaningless. Watch for it when testing.
6. **Keep `_on_transport` cheap.** It runs on the MIDI reader thread; anything
   heavy there stalls the clock and wrecks the tempo readout. Defer via
   `_defer()` to the listener thread.
7. **`restart.sh`, not `pkill -f`** (kills your own shell), and **wait for the
   MIDI port to free** before restarting (else garbled replies, "pppp777").
8. **A write that the machine accepts only proves the fields you checked.**
   The sample tone-record layout looked fine and played, but was wrong — compare
   against several device-made records. `deleteTone` is dead on 2.51; reuse a
   tone's own span. Heavy sample-index writing can crash the machine; a power
   cycle recovers it (and heals the fragmented free-space index).

## The assistant

- Backend choice in `Studio.init_chat`: Agent SDK (`agent.py`) if installed
  and `claude` is on PATH, else the plain API loop (`chat.py`).
- Credential: `claude auth status --json` (subscription) or the key kept in
  `studio.json` (mode 600); the user picks with `POST /api/auth/mode`.
  Sign-in: `POST /api/auth/login` runs `claude auth login` under a pty and
  streams its lines (`auth` events) so the UI can show the URL.
- Controls: `/api/chat` (one turn, blocking; events stream over SSE as
  `{"type":"chat","event":{...}}` — wrapped, never merged), `/api/chat/stop`,
  `/api/chat/reset`, `/api/chat/model`, `/api/chat/status`.
- `agent.on_machine_moved` is how a `device.select` by the assistant moves the
  studio too (no Program Change is sent for a SysEx select).
- Cost shown in `done` events is the API-equivalent estimate; on a
  subscription it is not billed.

## Testing without hands on the machine

You often can't press physical buttons. Two tricks used this session:
- `/api/inject` feeds raw MIDI into the monitor as if the machine sent it
  (proved knob-follow and the split-Program-Change fix).
- `/api/simulate_panel_edit {variation, instrument, index, value}` changes one
  step on the machine **without** telling the studio (`send_blob`, no
  `remember`) — a panel edit without a hand. The stopped-poll must pick it up
  within ~3s and log `user`. Do it on a slot the user is not working on, then
  put the step back. **Caveat:** it writes the slot the *studio* shows, so it
  cannot reproduce a desync between studio and machine — that was the actual
  bug, and only watching `/api/state` against the machine's own Program
  Changes while the user played showed it (LESSONS.md, "five small bugs").
- The SSE stream is the best debugger: `curl -sN localhost:8733/api/events`
  into a file with timestamps, then compare with what the user says they did.

## What's next

The `ROADMAP.md` is the ordered list. The highest-leverage open items:
- **Music intelligence in the chat prompt** — "hypnotic", "rolling", "peak
  time" should map to concrete steps/tones, not a guess.
- **Pattern critique from real audio** — record a whole pattern and say useful
  things (kick clipping, hole at 200 Hz, hats masking the ride).
- **A curated in-repo pattern library**, loadable by name.
- **Performance** — variation chaining, timed fills, mute groups. (Note: the
  user runs multi-variation chains on the machine; recognition can wobble across
  a chain — single-variation is solid.)
- **Startup desync** — the studio starts on `--slot` while the machine may be
  elsewhere and says nothing until the dial moves (no readable current
  pattern). Options: remember the last followed slot, or drive the machine to
  the studio's slot at start (`device.select`, works with Rx Prog Chg off).
- **Slot vs PC-value mapping** — one loose end: a followed Program Change value
  and `slot_to_panel` disagreed once in testing (PC 100 showed panel 8-09). Worth
  confirming the PC-number ↔ linear-slot mapping is identity for all banks.
