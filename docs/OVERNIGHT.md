# Overnight session — 2026-08-28 → 29

What was built while you slept, what I broke and fixed, and what needs your
eyes. Read the last section first if you only read one.

---

## Run it

```bash
cd ~/tr8s
.venv/bin/tr8s-studio            # http://127.0.0.1:8733
```

Three entry points are installed (`pip install -e .` into `.venv`):

| Command | What it is |
|---|---|
| `tr8s` | CLI over the tool registry — `tr8s info`, `tr8s tools`, `tr8s patterns 0 15`, `tr8s tones --category BASS --melodic`, `tr8s backup` |
| `tr8s-studio` | The web UI: live machine view + chat panel |
| `tr8s-mcp` | MCP server on stdio, for Claude Desktop / Claude Code / any MCP client |

**Run one at a time.** They all open the same MIDI node, and the OS lets them —
but incoming bytes go to whichever reader asks first, so two processes split the
stream and both see corruption.

## The studio

- **Machine view** — 11 instruments × 16 steps, variations A–H, the pattern
  header, and a kit strip showing which tone each instrument holds with its
  measured root. Melodic (sample) tones are highlighted.
- **Live playhead** — follows the TR-8S's own MIDI clock, so the column and the
  BPM readout track the machine exactly. Press play and watch it.
- **Click to edit** — cycles `·` → `o` → `x` → `X`. Each click writes the slot
  and you hear it on the next loop. **`WRITE` is what makes it survive
  power-off.** There is no undo.
- **Five themes** — phosphor, amber, ice, magenta, paper. The whole palette is
  CSS custom properties on `:root`; adding one means copying a block.

## Chat

Needs credentials this machine doesn't have:

```bash
export ANTHROPIC_API_KEY=sk-...     # or: ant auth login
```

Without them the machine view works fine and the panel says so. **The MCP server
needs no key of its own** — the client brings the model:

```json
{"mcpServers": {"tr8s": {"command": "/home/svh/tr8s/.venv/bin/tr8s-mcp"}}}
```

It exposes all 21 tools plus three resources, including a constraints document
that tells an agent what it must not promise (MOTION [ON], sample-only Coarse
Tune, fader-owned level).

**The chat path is untested end to end.** Tool schemas, the registry wiring and
the loop's shape are verified; the actual request/response round trip is not,
because there were no credentials here. It is the first thing to try, and the
first thing likely to need a fix.

---

## Corrections to what I told you earlier

**1. `commit` does not work the way I said.** I documented — and told you during
the jam — that a transfer without commit lands in a scratch buffer and changes
nothing. That is wrong. **Any transfer writes the slot immediately**, patterns
and kits alike. Proof: an uncommitted write to slot 116 survived a later
uncommitted write to 117; a single buffer cannot hold both.

The real difference is only whether the device re-reads the slot into what it is
playing — patterns do (hence live editing), kits do not. What `commit` adds is
presumably durability across power-off, which I could not test without a power
cycle.

**Consequence: the live jam overwrote `8-05`.** I have rebuilt I FEEL LOVE-ISH
there and verified it byte-exact.

**2. My testing damaged two patterns, both now repaired.**
- `8-07 MELODIC TECHNO` variation A had a row of accents on `HC` plus stray
  `SD`/`RS` hits from the buffer experiment. Rebuilt; your kit choices and the
  tempo were left alone.
- `1-07 DETROIT` pointed at kit 124 (the empty scratch slot) instead of 28
  `Detroit Love`. Reset.

I audited all 30 style slots: 29 were untouched, and that was the one.

**3. Your kit edits are intact and visible.** The kit strip shows `LT Heavy
Future Bs2`, `MT Electro House Bs`, `CC Syn.Str minor7th` — your sample swaps,
not my original picks.

---

## Also done

- **Tone catalogue**: 87 melodic tones measured for real root pitch, loudness,
  decay and brightness (`tones.json`). This is what fixes sounds not fitting
  together — I had been guessing roots, and e.g. `SoftPad minor7th` actually
  roots at D♯1, so it was playing a D♯ minor chord under a C minor melody.
- **Writes are 5× faster**: 2.05s → 0.38s for a 24504-byte pattern, by cutting
  the chunk pacing to 4 ms and dropping the per-chunk ack wait. Verified
  byte-exact over repeated trials at each step down.
- **65 offline tests** (`.venv/bin/python -m pytest`), including a fake
  transport that replays captured blobs, so the device and tool layers are
  covered without hardware.
- **No hardcoded paths.** Data resolves via `$TR8S_DATA` → XDG →
  `~/.local/share/tr8s`; the MIDI port is discovered from `/proc/asound`.

## Needs your attention

1. **Try the chat** with a key. Untested path.
2. **Power-cycle and confirm** the patterns I rebuilt are still there — that
   also settles what `commit` actually does, which is the last unknown in the
   protocol.
3. **Listen to `8-07`** variations A→H and `8-05`, and tell me anything that
   sounds wrong. My ears are measurements; yours are the spec.
4. The old `midi/` scripts still have `/home/svh` hardcoded. They produced
   everything currently on the machine, so I left them rather than break a
   working setup, but the package supersedes them.
