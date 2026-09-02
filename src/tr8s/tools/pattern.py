"""pattern tools — see the package docstring for the conventions."""

from __future__ import annotations

import inspect
import re
import subprocess
from pathlib import Path

from .. import config
from ..device import Device, DeviceError, panel_to_slot, slot_to_panel
from ..history import HISTORY
from ..kit import FIELDS as KIT_FIELDS
from ..kit import TRACKS, Kit
from ..melody import MelodyError
from ..melody import read as melody_read
from ..melody import write as melody_write
from ..pattern import VARIATIONS, Pattern
from ..tones import Catalog
from ._core import (DEFAULT_KEYS, DEFAULT_LINE, REGISTRY, ToolError,
                    _library_dir, _slot, opt, tool)
from ._core import device as _device_helper

@tool("pattern.list",
      "Names, tempos and kit assignments for a range of pattern slots.",
      {"lo": opt({"type": ["integer", "string"]}),
       "hi": opt({"type": ["integer", "string"]})})
def pattern_list(lo=0, hi=15):
    d = _device_helper()
    out = []
    for s in range(_slot(lo), _slot(hi) + 1):
        try:
            p = d.read_pattern(s)
        except DeviceError:
            continue
        out.append({"slot": s, "panel": slot_to_panel(s), "name": p.name,
                    "tempo": p.tempo, "kit": p.kit,
                    "variations": sorted(p.describe()["variations"])})
    return out




@tool("pattern.get", "Full contents of one pattern: header plus every "
      "variation's steps.",
      {"slot": {"type": ["integer", "string"],
                "description": "0..127 or a panel string like '8-03'"}})
def pattern_get(slot):
    s = _slot(slot)
    p = _device_helper().read_pattern(s)
    d = p.describe()
    d.update(slot=s, panel=slot_to_panel(s))
    return d




@tool("pattern.set_header",
      "Change a pattern's name, tempo, kit, scale or shuffle. Only the fields "
      "you pass are altered. NOTE: per-pattern tempo/shuffle/kit are ignored "
      "unless UTILITY GENERAL TempoSrc/Shuffle/KitSel are set to PTN.",
      {"slot": {"type": ["integer", "string"]},
       "name": opt({"type": "string"}),
       "tempo": opt({"type": "number", "minimum": 40, "maximum": 300}),
       "kit": opt({"type": "integer", "minimum": 0, "maximum": 127,
                   "description": "0-based kit index; the panel shows this + 1"}),
       "scale": opt({"type": "string", "enum": ["8T", "16T", "16", "32"]}),
       "shuffle": opt({"type": "integer", "minimum": -128, "maximum": 127}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_set_header(slot, name=None, tempo=None, kit=None, scale=None,
                       shuffle=None, commit=True):
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    if name is not None:
        p.name = name
    if tempo is not None:
        p.tempo = tempo
    if kit is not None:
        p.kit = kit
    if scale is not None:
        p.scale = scale
    if shuffle is not None:
        p.shuffle = shuffle
    return d.write_pattern(s, p, commit=commit)




@tool("pattern.set_steps",
      "Write one instrument's 16 steps in a variation. Notation: X accent, "
      "x normal, o ghost, . rest.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "steps": {"type": "string",
                 "description": "up to 16 chars of X x o ., e.g. 'X...x...X...x...'"},
       "commit": opt({"type": "boolean",
                      "description": "false skips the WRITE step. The slot still changes and you still hear it -- commit is what is presumed to make it survive power-off. It is not an undo."})},
      mutates=True)
def pattern_set_steps(slot, variation, instrument, steps, commit=True):
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    p.set_steps(variation, instrument, steps)
    r = d.write_pattern(s, p, commit=commit)
    r["steps"] = p.get_steps(variation, instrument)
    return r




@tool("pattern.set_many",
      "Write several instruments' steps into one variation in a single "
      "device write. Much faster than repeated pattern.set_steps.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "tracks": {"type": "object",
                  "description": "instrument -> step string, e.g. "
                                 "{\"BD\":\"X...x...X...x...\"}"},
       "clear": opt({"type": "boolean",
                     "description": "clear the variation first (default true)"}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_set_many(slot, variation, tracks, clear=True, commit=True):
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    if clear:
        p.clear_variation(variation)
    for inst, steps in tracks.items():
        p.set_steps(variation, inst, steps)
    r = d.write_pattern(s, p, commit=commit)
    r["tracks"] = p.variation_summary(variation)
    return r




@tool("pattern.audit",
      "Criticise a variation before you hear it, using each tone's MEASURED "
      "brightness and decay against where its hits land. Catches the low end "
      "colliding (a kick and a bassline on the same step cancel rather than "
      "add), parts masking each other, and tones that decay for longer than "
      "the gap between their own hits at this tempo. Advisory: level belongs "
      "to the faders, so the fixes are about moving hits and choosing tones.",
      {"slot": {"type": ["integer", "string"]},
       "variation": opt({"type": "string", "enum": list(VARIATIONS)}),
       "tempo": opt({"type": "number",
                     "description": "override the pattern header, which the "
                                    "machine ignores unless set to PTN"})})
def pattern_audit(slot, variation="A", tempo=None):
    from ..audit import audit
    d = _device_helper()
    p = d.read_pattern(_slot(slot))
    k = d.read_kit(p.kit)
    return audit(p, k, d.catalog, variation=variation, tempo=tempo)




@tool("pattern.generate",
      "Generate one variation in a named style and write it. This is the way "
      "to make a pattern -- typing step strings by hand does not survive a "
      "request like 'same but sparser'. The seed is returned, so a bar that "
      "worked can be asked for again, or regenerated at a different energy.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "style": {"type": "string",
                 "description": "one of styles.list, e.g. techno, hypnotic, "
                                "dub, acid, hard, broken, dnb, lofi, house"},
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "role": opt({"type": "string",
                    "description": "intro | main | break | fill | drop"}),
       "seed": opt({"type": "integer"}),
       "set_tempo": opt({"type": "boolean",
                         "description": "also write the style's tempo to the "
                                        "pattern header. Default false, since "
                                        "the header is ignored unless UTILITY "
                                        "GENERAL is set to PTN."}),
       "keep": opt({"type": "boolean",
                    "description": "merge with what is already there instead "
                                   "of replacing the variation"}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_generate(slot, variation, style="techno", energy=0.6, role="main",
                     seed=None, set_tempo=False, keep=False, commit=True):
    from ..style import generate
    s = _slot(slot)
    d = _device_helper()
    try:
        g = generate(style, energy=energy, role=role, seed=seed)
    except ValueError as e:
        raise ToolError(str(e)) from None

    p = d.read_pattern(s)
    if not keep:
        p.clear_variation(variation)
    for inst, steps in g["tracks"].items():
        p.set_steps(variation, inst, steps)
    if set_tempo:
        p.tempo = g["tempo"]
    r = d.write_pattern(s, p, commit=commit)
    r.update(style=g["style"], role=g["role"], energy=g["energy"],
             seed=g["seed"], tempo=g["tempo"],
             tracks=p.variation_summary(variation))
    return r




@tool("pattern.arrange",
      "Fill all eight variations as one track: intro, main, build, fill, "
      "break, drop, peak. A-H stop being eight unrelated loops. Returns the "
      "seed and the per-variation roles.",
      {"slot": {"type": ["integer", "string"]},
       "style": {"type": "string"},
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "seed": opt({"type": "integer"}),
       "name": opt({"type": "string", "description": "pattern name, <= 8 chars"}),
       "set_tempo": opt({"type": "boolean"}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_arrange(slot, style="techno", energy=0.6, seed=None, name=None,
                    set_tempo=False, commit=True):
    from ..style import arrangement
    s = _slot(slot)
    d = _device_helper()
    try:
        a = arrangement(style, seed=seed, energy=energy)
    except ValueError as e:
        raise ToolError(str(e)) from None

    p = d.read_pattern(s)
    roles = {}
    for v, g in a["variations"].items():
        p.clear_variation(v)
        for inst, steps in g["tracks"].items():
            p.set_steps(v, inst, steps)
        roles[v] = g["role"]
    if name:
        p.name = name
    if set_tempo:
        p.tempo = a["tempo"]
    r = d.write_pattern(s, p, commit=commit)
    r.update(style=style, seed=a["seed"], tempo=a["tempo"], roles=roles)
    return r




@tool("pattern.clear_variation", "Erase every step and motion in one variation.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_clear_variation(slot, variation, commit=True):
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    p.clear_variation(variation)
    return d.write_pattern(s, p, commit=commit)




@tool("pattern.set_melody",
      "Write a melody as note names onto one instrument. Uses Coarse Tune "
      "motion (four octaves) by default, which needs a SAMPLE tone with Coarse "
      "Tune on its CTRL knob and MOTION [ON] lit. 'root' is the note the tone "
      "sounds at untuned -- look it up with tones.search rather than guessing, "
      "as a wrong root transposes the whole line.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "notes": {"type": "string",
                 "description": "up to 16 space-separated notes or '.' rests, "
                                "e.g. 'C2 . G2 C3 . D#3 G3 .'"},
       "root": {"type": "string", "description": "the tone's natural pitch, e.g. 'C3'"},
       "mode": opt({"type": "string", "enum": ["coarse", "fine"]}),
       "velocity": opt({"type": "integer", "minimum": 1, "maximum": 127}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_set_melody(slot, variation, instrument, notes, root,
                       mode="coarse", velocity=104, commit=True):
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    warnings = melody_write(p, variation, instrument, notes, root,
                            mode=mode, velocity=velocity)
    r = d.write_pattern(s, p, commit=commit)
    r["melody"] = melody_read(p, variation, instrument, root, mode=mode)
    r["warnings"] = warnings
    # both of these are panel state, not blob state: nothing here can set them
    # or check them, so say plainly what the player has to do
    steps = ["MOTION [ON] must be lit"]
    if mode == "coarse":
        steps.append(f"Coarse Tune must be assigned to {instrument}'s CTRL knob "
                     f"(hold [CTRL SELECT], press {instrument}, pick Coarse Tune) "
                     f"-- otherwise the motion moves whatever else is assigned")
    r["panel_setup"] = steps
    return r




@tool("pattern.set_line",
      "Generate a line in key and write it to an instrument in one step. The "
      "tone's real root is looked up from the measured catalogue, so the line "
      "comes out in the key asked for instead of transposed by whatever the "
      "sample happens to be tuned to. Shapes: bass (the offbeat pulse), acid "
      "(a 303 line with accents), stab (dub techno's offbeat chord), arp. "
      "Needs a SAMPLE tone with Coarse Tune on the instrument's CTRL knob.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "shape": {"type": "string", "enum": ["bass", "acid", "stab", "arp"]},
       "key": opt({"type": "string"}),
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "seed": opt({"type": "integer"}),
       "root": opt({"type": "string",
                    "description": "override the catalogue's measured root"}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_set_line(slot, variation, instrument, shape, key="C minor",
                     energy=0.6, seed=None, root=None, commit=True):
    from ..lines import generate as gen
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)

    resolved = root
    source = "caller"
    if resolved is None:
        # the whole point: look the pitch up rather than assume it
        k = d.read_kit(p.kit)
        info = d.tone_info(k.get(instrument, "tone"))
        resolved = getattr(info, "root", None) if info else None
        source = "catalogue"
        if not resolved:
            raise ToolError(
                f"{instrument}'s tone has no measured root, so a line would "
                f"come out at an unknown pitch. Give `root`, or pick a tone "
                f"with tones.search(melodic=true).")
        if info and info.type != 2:
            raise ToolError(
                f"{instrument} is on '{info.name}', an ACB tone with no Coarse "
                f"Tune -- it can only bend a few semitones. Use "
                f"tones.search(melodic=true) to find a sample tone first.")

    try:
        line = gen(shape, key=key, energy=energy, root=resolved, seed=seed)
    except ValueError as e:
        raise ToolError(str(e)) from None

    warnings = melody_write(p, variation, instrument, line["notes"], resolved,
                            mode="coarse")
    for i in line.get("accents") or []:
        cur = list(p.get_steps(variation, instrument))
        if cur[i] != ".":
            cur[i] = "X"
        p.set_steps(variation, instrument, "".join(cur))

    r = d.write_pattern(s, p, commit=commit)
    r.update(shape=shape, key=key, energy=energy, seed=line["seed"],
             root=resolved, root_from=source, notes=line["notes"],
             warnings=warnings + line["warnings"])
    r["panel_setup"] = [
        "MOTION [ON] must be lit",
        f"Coarse Tune must be assigned to {instrument}'s CTRL knob "
        f"(hold [CTRL SELECT], press {instrument}, pick Coarse Tune)",
    ]
    return r




@tool("pattern.get_melody", "Read a melody back from a pattern as note names.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "root": {"type": "string"},
       "mode": opt({"type": "string", "enum": ["coarse", "fine"]})})
def pattern_get_melody(slot, variation, instrument, root, mode="coarse"):
    p = _device_helper().read_pattern(_slot(slot))
    return {"melody": melody_read(p, variation, instrument, root, mode=mode)}




@tool("pattern.set_note",
      "Change a single step's note without rewriting the rest of the line. "
      "Use this to fix one wrong note, rather than re-sending the whole melody "
      "-- which would clear any hits the melody did not put there. A null note "
      "clears the step to a rest, motion and all. Coarse Tune reaches 24 "
      "semitones either side of the root.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "step": {"type": "integer", "minimum": 1, "maximum": 16,
                "description": "1-based, as printed on the panel"},
       "note": {"type": ["string", "null"],
                "description": "e.g. 'A#3', or null for a rest"},
       "root": {"type": "string",
                "description": "the tone's natural pitch -- from tones.search"},
       "velocity": opt({"type": "integer", "minimum": 1, "maximum": 127}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_set_note(slot, variation, instrument, step, note, root,
                     velocity=104, commit=True):
    from ..melody import COARSE_MAX, COARSE_MIN, COARSE_OFFSET, note_to_midi
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    i = step - 1

    root_midi = note_to_midi(root)
    if root_midi is None:
        raise ToolError("root must be a real note, e.g. C2")
    cur = p.get_steps(variation, instrument)

    if note is None:
        p.clear_motion(variation, instrument, i)
        steps = cur[:i] + "." + cur[i + 1:]
    else:
        midi = note_to_midi(note)
        if midi is None:
            raise ToolError("note must be a real note, or null for a rest")
        semis = midi - root_midi
        if not COARSE_MIN <= semis <= COARSE_MAX:
            raise ToolError(f"{note} is {semis:+d} semitones from {root}, "
                            f"outside Coarse Tune's {COARSE_MIN}..{COARSE_MAX}")
        p.set_motion(variation, instrument, i, ctrl=semis + COARSE_OFFSET)
        # a step that never fires has nothing to bend, so give it a hit
        hit = "X" if velocity >= 112 else "x" if velocity >= 90 else "o"
        steps = cur[:i] + (cur[i] if cur[i] != "." else hit) + cur[i + 1:]
    p.set_steps(variation, instrument, steps)

    r = d.write_pattern(s, p, commit=commit)
    r["note"] = note
    r["steps"] = steps
    r["melody"] = melody_read(p, variation, instrument, root)
    return r




@tool("pattern.transpose",
      "Shift an instrument's melody by a number of semitones, in place. Use "
      "this when a line was written against the wrong root and sounds in the "
      "wrong octave or key -- it rewrites the motion rather than the notes.",
      {"slot": {"type": ["integer", "string"]},
       "variation": {"type": "string", "enum": list(VARIATIONS)},
       "instrument": {"type": "string", "enum": TRACKS},
       "semitones": {"type": "integer", "minimum": -48, "maximum": 48},
       "mode": opt({"type": "string", "enum": ["coarse", "fine"]}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_transpose(slot, variation, instrument, semitones,
                      mode="coarse", commit=True):
    from ..melody import COARSE_MAX, COARSE_MIN, FINE_UNITS_PER_SEMITONE
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    moved, warnings = 0, []
    for step in range(16):
        m = p.get_motion(variation, instrument, step)
        if not m["mask"]:
            continue
        if mode == "coarse":
            if m["ctrl"] is None:
                continue
            cur = m["ctrl"] - 24
            new = cur + semitones
            if not COARSE_MIN <= new <= COARSE_MAX:
                warnings.append(
                    f"step {step + 1}: {new:+d} semitones is outside Coarse "
                    f"Tune's {COARSE_MIN}..{COARSE_MAX}; clamped")
                new = max(COARSE_MIN, min(COARSE_MAX, new))
            p.set_motion(variation, instrument, step, ctrl=new + 24)
        else:
            if m["tune"] is None:
                continue
            units = m["tune"] + int(round(semitones * FINE_UNITS_PER_SEMITONE))
            if not -128 <= units <= 127:
                warnings.append(
                    f"step {step + 1}: outside fine tune's range; clamped")
                units = max(-128, min(127, units))
            p.set_motion(variation, instrument, step, tune=units)
        moved += 1
    if not moved:
        raise ToolError(
            f"{instrument} has no {mode} tune motion in variation {variation}; "
            f"nothing to transpose")
    r = d.write_pattern(s, p, commit=commit)
    r.update(transposed_steps=moved, semitones=semitones, warnings=warnings)
    return r




@tool("pattern.copy", "Copy one pattern slot to another.",
      {"source": {"type": ["integer", "string"]},
       "dest": {"type": ["integer", "string"]},
       "name": opt({"type": "string"})}, mutates=True)
def pattern_copy(source, dest, name=None):
    d = _device_helper()
    p = d.read_pattern(_slot(source))
    if name:
        p.name = name
    return d.write_pattern(_slot(dest), p)




@tool("pattern.copy_variation",
      "Copy one variation onto another within a pattern -- the usual way to "
      "build an arrangement: make the main groove, copy it, then edit.",
      {"slot": {"type": ["integer", "string"]},
       "source": {"type": "string", "enum": list(VARIATIONS)},
       "dest": {"type": "string", "enum": list(VARIATIONS)},
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_copy_variation(slot, source, dest, commit=True):
    if source == dest:
        raise ToolError("source and dest are the same variation")
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    p.clear_variation(dest)
    for inst in TRACKS:
        steps = p.get_steps(source, inst)
        if steps.strip("."):
            p.set_steps(dest, inst, steps)
        for step in range(16):
            m = p.get_motion(source, inst, step)
            if m["mask"]:
                p.set_motion(dest, inst, step,
                             tune=m["tune"], ctrl=m["ctrl"])
    r = d.write_pattern(s, p, commit=commit)
    r["copied"] = {"from": source, "to": dest,
                   "tracks": sorted(p.variation_summary(dest))}
    return r




@tool("pattern.export",
      "Export a pattern as plain JSON: header, every variation's steps, and any "
      "melodies as note names. Round-trips through pattern.import, so patterns "
      "can be kept in version control and shared.",
      {"slot": {"type": ["integer", "string"]},
       "roots": opt({"type": "object",
                     "description": "instrument -> root note, for reading "
                                    "melodies back. Defaults to each tone's "
                                    "measured root from the catalogue."}),
       "ctrl_is_coarse_tune": opt({"type": "boolean",
                                   "description": "default false. CTRL motion "
                                                  "is only pitch when Coarse "
                                                  "Tune is assigned to the CTRL "
                                                  "knob, which software cannot "
                                                  "read; otherwise it exports "
                                                  "as raw values."})})
def pattern_export(slot, roots=None, ctrl_is_coarse_tune=False):
    from ..melody import read as melody_read
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    roots = dict(roots or {})
    # roots are a convenience: without them melodies export as raw values
    # rather than notes, which is still a faithful document
    try:
        k = d.read_kit(p.kit)
        for inst in TRACKS:
            if inst in roots:
                continue
            info = d.tone_info(k.get(inst, "tone"))
            if info and getattr(info, "root", None):
                roots[inst] = info.root
    except DeviceError:
        pass

    out = {"name": p.name, "tempo": p.tempo, "kit": p.kit, "scale": p.scale,
           "shuffle": p.shuffle, "roots": roots, "variations": {}}
    for v in VARIATIONS:
        tracks = p.variation_summary(v)
        if not tracks:
            continue
        entry = {"tracks": tracks}
        melodies = {}
        for inst in tracks:
            motion = [p.get_motion(v, inst, st) for st in range(16)]
            if not any(m["mask"] for m in motion):
                continue
            has_ctrl = any(m["ctrl"] is not None for m in motion)
            mode = "coarse" if has_ctrl else "fine"
            root = roots.get(inst)
            # Byte +0 is always Tune, so fine motion is unambiguously pitch.
            # CTRL is whatever is assigned to that instrument's CTRL knob --
            # Coarse Tune, or pan, or a send. That assignment is not in the kit
            # blob, so reading CTRL as semitones is only valid when the caller
            # says so. Otherwise export raw values rather than invent notes.
            as_notes = bool(root) and (mode == "fine" or ctrl_is_coarse_tune)
            if not as_notes:
                melodies[inst] = {
                    "mode": mode,
                    "raw": [{"step": st, "tune": m["tune"], "ctrl": m["ctrl"]}
                            for st, m in enumerate(motion) if m["mask"]],
                }
                if has_ctrl and root and not ctrl_is_coarse_tune:
                    melodies[inst]["note"] = (
                        "CTRL motion exported as raw values: pass "
                        "ctrl_is_coarse_tune=true if Coarse Tune is assigned "
                        "to this instrument's CTRL knob")
                continue
            melodies[inst] = {"mode": mode, "root": root,
                              "notes": melody_read(p, v, inst, root, mode=mode)}
        if melodies:
            entry["melodies"] = melodies
        out["variations"][v] = entry
    out["slot"] = s
    out["panel"] = slot_to_panel(s)
    return out




@tool("pattern.import",
      "Write a pattern from the JSON that pattern.export produces. Only the "
      "fields present are applied, so a partial document edits in place.",
      {"slot": {"type": ["integer", "string"]},
       "pattern": {"type": "object", "description": "a pattern.export document"},
       "clear": opt({"type": "boolean",
                     "description": "clear each named variation first (default true)"}),
       "commit": opt({"type": "boolean"})}, mutates=True)
def pattern_import(slot, pattern, clear=True, commit=True):
    from ..melody import write as melody_write
    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    warnings = []

    for field in ("name", "tempo", "scale", "shuffle"):
        if field in pattern:
            setattr(p, field, pattern[field])
    if "kit" in pattern:
        p.kit = pattern["kit"]

    roots = pattern.get("roots") or {}
    for v, entry in (pattern.get("variations") or {}).items():
        if clear:
            p.clear_variation(v)
        for inst, steps in (entry.get("tracks") or {}).items():
            p.set_steps(v, inst, steps)
        for inst, mel in (entry.get("melodies") or {}).items():
            mode = mel.get("mode", "coarse")
            if "notes" in mel:
                root = mel.get("root") or roots.get(inst)
                if not root:
                    warnings.append(
                        f"{v}/{inst}: notes given without a root, skipped -- "
                        f"a guessed root would transpose the line")
                    continue
                warnings += [f"{v}/{inst}: {w}" for w in
                             melody_write(p, v, inst, mel["notes"], root,
                                          mode=mode)]
                # melody_write owns the step pattern; restore any explicit one
                if (entry.get("tracks") or {}).get(inst):
                    p.set_steps(v, inst, entry["tracks"][inst])
            else:
                for item in mel.get("raw", []):
                    p.set_motion(v, inst, item["step"],
                                 tune=item.get("tune"), ctrl=item.get("ctrl"))
    r = d.write_pattern(s, p, commit=commit)
    r["warnings"] = warnings
    r["variations"] = sorted(pattern.get("variations") or {})
    return r


# ======================================================================= kit

