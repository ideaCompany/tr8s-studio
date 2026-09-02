# TR-8S Studio

**Talk to your Roland TR-8S. Get a track back.**

An open-source studio for the Roland TR-8S drum machine: a web UI that mirrors
the machine live, a reverse-engineered SysEx layer that reads and writes every
pattern and kit byte-exact, and an AI assistant that turns "make me a warm
house track with a real bassline" into a finished, playing pattern in about a
minute, using your own Claude subscription.

> "Make me a house track on 8-02, warm and classic, around 124 BPM, with a
> real bassline."
>
> 74 seconds later: a kit chosen from measured tones, eight arranged
> variations, a walking bassline in A minor, the machine switched to it, the
> seed reported, undo offered.

![The assistant building a house track while it explains what it is doing](docs/screenshots/03-house-track-built.jpg)

## What it does

**A studio that follows the machine.** Change pattern on the TR-8S and the
studio is there. Play it and every step lights as it sounds, the variation
letter is recognised by ear, knobs and faders move on screen as you touch
them. Add a step on the panel while it plays and TRACK jumps to that
instrument within a bar. Nothing is polled; the machine is the source of
truth.

![The panel view while the machine plays: playhead, live steps, recognised variation](docs/screenshots/05-playing-panel.jpg)

**Editing that is live.** Click a step in the grid or on the pads and the
machine has it before the bar comes round. A write lands in what is playing,
so there is no "load", no "send", no waiting for a stop.

![The grid view: all eleven instruments across sixteen steps, playing](docs/screenshots/06-grid-view-playing.jpg)

**An assistant that works the way a collaborator does.** It sees what you
see: the pattern on screen, whether the machine is playing, which variation is
heard, what changed recently and who changed it. It reasons out loud, calls
the studio's tools, and tells you in musical terms what it did.

- *"The clap needs more snap, and give the hats a little swing."*
  It swapped the clap for a shorter, brighter one chosen by measured decay and
  brightness, centred its pan, and set shuffle, then told you the one caveat
  that matters on this machine.
- *"Play it, then tell me what to press to hear the bassline."*
  It started the transport and walked you through Coarse Tune and MOTION ON,
  which the hardware needs and cannot do for you.
- *"Stop, and summarise what we built."*
  Five lines, both tracks from the session, seeds included, and a correction
  of something it had said earlier about undo.

![Sound swap and swing, with the assistant's reasoning shown](docs/screenshots/04-clap-and-swing.jpg)

**Sounds chosen from data, not names.** Every melodic tone on the machine has
been measured: the note it really sounds at, how long it rings, how bright it
is. "A darker, shorter kick" is a query, not a guess, and a bassline comes out
in key because the tone's real root is looked up first.

**Melodies the hardware makes almost impossible by hand.** Per-step Coarse
Tune motion, four octaves, exact semitones, written as note names.

**A memory.** A colour-coded change log records what the user did on the
panel, what the studio did, and what the assistant did, and it survives
restarts. So does the conversation.

**Safety rails.** Every mutating tool snapshots the slot it is about to
change, so there is an undo ring. The assistant reads before it overwrites
and says what it is replacing.

## Bring your own assistant

![Connect an assistant: Claude sign-in or an API key](docs/screenshots/01-connect-assistant.jpg)

- **Claude, with the subscription you already have.** Sign in once through the
  browser; the studio shows who is signed in and on which plan. This runs on
  the Claude Agent SDK, which drives the same `claude` binary you use in the
  terminal.
- **Claude with an API key.** Three steps in the UI, a TEST button that makes a
  real call, then USE.
- **Any MCP client.** Claude Desktop, Cursor and friends can drive the machine
  through `tr8s-mcp` with their own sign-in.
- OpenAI and Gemini backends are on the list; the tool registry is
  provider-neutral and contributions here are very welcome.

*A note on terms: Anthropic's Agent SDK documentation does not allow
third-party products to offer claude.ai login without approval. Signing in
with your own account on your own machine, as this studio does, is personal
use. Do not redistribute a hosted version of this with subscription login.*

## Quick start

```bash
git clone <this repo> && cd tr8s
python3 -m venv .venv && .venv/bin/pip install -e . claude-agent-sdk anthropic
# plug in the TR-8S over USB, then:
scripts/restart.sh                     # finds the MIDI port, starts the studio
# open http://127.0.0.1:8733
```

For the assistant, either have [Claude Code](https://claude.com/code)
installed and signed in (`claude auth login`), or paste an API key in the
studio's connect panel. `scripts/restart.sh --offline` runs the UI without a
machine.

On the TR-8S, three settings make the studio's life easy: UTILITY → MIDI →
**Tx Prog Chg ON** (pattern follow), **Tx EditData ON** (knob follow and the
beat counter), and UTILITY → GENERAL → tempo, shuffle and kit sources set to
**PTN** so per-pattern settings are honoured.

## Under the hood

- `src/tr8s/transport.py`, `device.py`, `pattern.py`, `kit.py` — the wire
  format and the models. The protocol is reverse-engineered and documented in
  [`docs/PROTOCOL.md`](docs/PROTOCOL.md), every claim marked verified or not.
- `src/tr8s/tools/` — 52 tools, one decorator each with a JSON schema. The
  same registry drives the CLI, the studio, the assistant and the MCP server.
- `src/tr8s/server.py` — the studio: HTTP + SSE, following, live overlay,
  panel-edit detection.
- `src/tr8s/agent.py` — the assistant on the Claude Agent SDK, tools served
  in-process as an MCP server (only this process can hold the MIDI port).
- `src/tr8s/web/` — vanilla HTML, JS and CSS. No build step.
- `docs/` — start with [`HANDOFF.md`](docs/HANDOFF.md);
  [`LESSONS.md`](docs/LESSONS.md) is every trap already hit, with the fix.

465 tests run without hardware against a fake transport. Verified against a
real TR-8S on firmware 2.51.

## Things the hardware imposes

Bulk SysEx reads hang while the machine plays, so the studio reads only when
it stops and hears the rest. The panel sends nothing when a step is toggled or
a variation is selected; both are recognised from what plays. Levels belong to
the physical faders and cannot be set. Melodies need Coarse Tune on the
instrument's CTRL knob and MOTION ON, by hand. The studio and the assistant
know all of this and say so at the moment it matters, not before.

## Contributing

This project moved from "can we even read a pattern" to "make me a house
track" in a few days, and there is plenty of room to run:

- **More assistants.** An OpenAI or Gemini backend over the same tool
  registry.
- **Music intelligence.** Better mappings from words ("hypnotic", "peak
  time", "dubby") to steps and tones; critique from recorded audio.
- **A pattern library** worth keeping, loadable by name, with what each is for.
- **Performance.** Variation chaining, timed fills, mute groups.
- **Other machines.** The architecture (transport, models, tools, studio,
  assistant) is not TR-8S specific in shape.

Read [`docs/HANDOFF.md`](docs/HANDOFF.md) first, then
[`docs/UX-NOTES.md`](docs/UX-NOTES.md) for known rough edges that are good
first issues. Run `pytest tests/` before and after.

## Licence

MIT. See [`LICENSE`](LICENSE).
