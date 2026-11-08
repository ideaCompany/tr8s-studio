**Title:** Synth tools, arrangement-aware parts, set builder and cue sheet

**Labels:** `rig`, `tools`, `fm-1`

## Context

With the part generator and encoder from issue 04, the studio needs:

- tools, so the CLI, the studio and the assistant can use them;
- a link from tracks to their FM-1 parts;
- a way to prepare a whole set for Live mode: what is on which slot, and when
  each synth comes in.

Two rules from [`docs/RIG-FM1.md`](../RIG-FM1.md):

- the studio **never sends MIDI clock** to the FM-1;
- **not every song is acid**, so the voicing table decides the parts.

## Tasks

**Sender**

- [ ] `synth/port.py`: open the FM-1's USB MIDI port by name with
      `python-rtmidi` (an optional extra; the core keeps zero dependencies).
      Send SysEx and wait for each reply, with a timeout and a useful error.
- [ ] **Refuse to send realtime bytes (`F8`–`FC`)**, with a test.

**Tools**: a new `synth` namespace. Add `"synth"` to the list in
`tools/__init__.py`, and follow `@tool` in `tools/_core.py`.

- [ ] `synth.parts` (pure): parts for a style, key, energy and seed, with an
      optional voicing override.
- [ ] `synth.export`: write `.json`, `.mid` and `.syx` into the library.
- [ ] `synth.send` (`mutates=True`): push parts or a project to the FM-1, then
      save.

**Integration with tracks**

- [ ] `track.create` and `track.remix` take an optional `synth` argument, for
      example `{"target": "minitone", "voicing": "dub", "project": 3}`. It
      builds the FM-1 parts from the same key, tempo, seed and arrangement as
      the drums. When it is given, the TR-8S's own melodic line defaults to
      `none`.
- [ ] Parts enter with the arrangement: the energy curve from
      `pattern.arrange` decides when each part plays. Encode it as Mini-Tone
      song sections A–D with per-section mutes.
- [ ] Library JSON gains an optional `"synth"` block. Library load and save
      round-trip it.

**Set builder**

- [ ] `set.build`: an ordered list of tracks (style, key, energy, seed,
      voicing) becomes TR-8S pattern slots, FM-1 project slots and a markdown
      cue sheet.
- [ ] The cue sheet lists, per track: the TR-8S slot with its FM-1 project,
      key, BPM and seed, which FM-1 parts play in each section, which EMP16 pad
      brings which part in, and the EMP16 knob map.

**Assistant**

- [ ] Add a short FM-1 section to the system prompt `SYSTEM` in `chat.py`
      (shared by `agent.py`): the voicings, the voice budget, that not every
      song needs a 303, and that the FM-1 follows the TR-8S's clock.

**Tests**

- [ ] Tool schemas and dispatch on a fake FM-1 port (in the style of
      `tests/fake.py`).
- [ ] `track.create` with `synth`: the parts share the drums' key and seed.
- [ ] `set.build` output, and a cue-sheet snapshot test.
- [ ] Library round-trip with a `synth` block.

## Acceptance

- `pytest tests/` passes.
- From the CLI, `set.build` for three tracks (one acid, one dub, one hypnotic)
  writes the TR-8S slots, writes and saves the FM-1 projects, and prints a cue
  sheet. With the laptop unplugged, the three tracks play from the boxes and
  the sheet.

## Depends on

Issue 04. Issue 03 only where the spike found something missing.

## Pipeline

Sonnet implements; Opus reviews.
