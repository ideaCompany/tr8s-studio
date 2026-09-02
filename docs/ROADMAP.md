# What this still needs

Written 2026-08-29, unprompted, as the working list. The goal it is measured
against: **you should be able to talk to the TR-8S and get great techno out of
it.** Everything below either makes the music better or makes the conversation
that produces it better.

Ordered by how much each one moves that goal.

**Done:** 1 groove engine, 2 kits from measurement, 3 scales, 4 acid, 5 undo,
6 arrangement (`pattern.arrange`), 7 a prompt that knows the music.
**Left:** 8 pattern critique, 9 a library, 10 performance.

### Update 2026-09-02 — the studio caught up to the machine

Since this list was written, a whole layer landed that is not in the numbered
items above: **the studio now follows the machine and can drive it back.**
Working and verified live (see `HANDOFF.md` for the full list): pattern-follow
via Program Change (playing too, after fixing a clock-split parse bug),
variation-follow by ear, the live heard-note overlay, knob/fader sync with
sweep-coalesced logging, panel step-edit detection on stop (read-back diff,
zero false positives), studio/AI edit logging with instrument auto-focus, a
tagged persisted **change log**, and sample import/fetch/hotswap while playing.

One deliberate non-goal recorded here so it is not attempted again lightly:
**detecting step edits by ear *while playing* is unreliable** (rolls, sub-steps,
pitched voices, swing) and is off by default. The reliable path is the
read-back on stop. Details and measurements in `LESSONS.md`.

## 1. A groove engine, not hand-typed step strings

Patterns are currently written as literal `"X...X...X...X..."`. That does not
scale to "make it darker and more hypnotic". Needs a `style` module that knows
how techno and its derivatives are actually built — offbeat hats, ghost
velocities, 3-against-4 percussion, kick weight, where the clap sits — and can
generate from `(style, energy, role, seed)`. Reproducible, so "same but
sparser" means something.

## 2. Kits assembled from the measured catalogue

The tone catalogue has `root`, `decay_ms`, `centroid` and `peak` for 614 tones.
That is enough to *choose* rather than guess: a kick and a bass line that do not
sit on the same note, hats bright enough to cut over the kick, no two elements
fighting at the same centroid. `kit.auto_build(style=...)` should pick a kit
that works before a single step is written.

## 3. Scale and key awareness

Melodies are written as absolute note names, so nothing stops a line that is out
of key. Techno lives in a handful of modes — natural minor, phrygian, and the
occasional dorian. Constrain generated lines to a scale, and let the whole
pattern share a key.

## 4. Acid

A 303 line is the single most recognisable sound in the genre and the TR-8S can
do it with Coarse Tune motion: octave jumps, accents, slides. Deserves its own
generator, not a generic melody.

## 5. Undo

The UI currently says "there is no undo", and that is true — every click writes
the slot. Vibing means making a mess and stepping back. A snapshot ring buffer
before every mutation fixes it, and costs 24 KB a step.

## 6. Arrangement across variations

A–H exist and are barely used. Intro, main, break, fill, drop written as one
coherent set, with the transitions techno relies on — hat density ramps, the bar
of silence before the drop, the clap that arrives late.

## 7. A system prompt that knows the music

The chat prompt states hardware constraints well and knows nothing about music.
It should know what "hypnotic", "peak time", "dubby", "rolling" mean in terms of
steps and tones, so those words produce the right pattern instead of a guess.

## 8. Listening to whole patterns, not just tones

Single-tone analysis worked. The same rig can record a pattern playing and say
useful things: the kick is clipping, there is a hole at 200 Hz, the hats are
masking the ride. Criticism, from the machine's actual output.

## 9. A pattern library worth keeping

`pattern.export` produces JSON. A curated set of good starting points, in the
repo, loadable by name, with the metadata that says what each is for.

## 10. Performance

Variation chaining, fills on a timer, mute groups. The part where you stop
editing and start playing.


## 2026-09-02 (later) — follow is real now

Panel-edit follow works with a hand on the panel, stopped and playing (see
LESSONS.md "five small bugs" and "TRACK by ear"). The tempo readout is steady.
Open: startup desync (above in HANDOFF "What's next").
