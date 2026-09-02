"""kit tools — see the package docstring for the conventions."""

from __future__ import annotations

import inspect
import re
import subprocess
import wave
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

@tool("kit.set_color",
      "Set an instrument's fader colour on the machine. The TR-8S lights each "
      "fader a colour that is saved with the kit. Colours are 0..11; the names "
      "are labels for the indices, since which index lights which colour has "
      "not been confirmed against the panel.",
      {"slot": {"type": ["integer", "string"], "description": "the KIT slot"},
       "colors": {"type": "object",
                  "description": "instrument -> colour index, e.g. "
                                 "{\"BD\": 0, \"SD\": 1}"}},
      mutates=True)
def kit_set_color(slot, colors):
    from ..kit import COLOUR_NAMES
    s = _slot(slot, "kit")
    d = _device_helper()
    k = d.read_kit(s)
    before = k.colors()
    for inst, idx in (colors or {}).items():
        if inst not in TRACKS:
            raise ToolError(f"unknown instrument {inst!r}; have {TRACKS}")
        k.set_color(inst, int(idx))
    r = d.write_kit(s, k)
    r["colors"] = {i: {"index": v, "name": COLOUR_NAMES[v]
                       if v < len(COLOUR_NAMES) else str(v)}
                   for i, v in k.colors().items()}
    r["changed"] = {i: [before[i], k.color(i)] for i in TRACKS
                    if before[i] != k.color(i)}
    r["note"] = ("the colour byte was identified from the kit format, not by "
                 "watching the panel -- check that the index you picked lights "
                 "the colour you expected")
    return r




@tool("kit.tune_to",
      "Tune an instrument so it SOUNDS at a given note, rather than nudging a "
      "raw number. Works out the shift from the tone's measured root and the "
      "calibrated TUNE law (one octave either way, linear). Use it to put the "
      "kick on the tonic of the track's key -- a kick a semitone off the bass "
      "beats against it on every downbeat.",
      {"slot": {"type": ["integer", "string"], "description": "the KIT slot"},
       "instrument": {"type": "string", "enum": TRACKS},
       "note": {"type": "string", "description": "e.g. 'C1', 'F#2'"},
       "root": opt({"type": "string",
                    "description": "override the catalogue's measured root"})},
      mutates=True)
def kit_tune_to(slot, instrument, note, root=None):
    from ..calibration import (TUNE_SEMITONE_RANGE, tune_byte_for_semitones,
                              tune_semitones_for_byte)
    from ..melody import note_to_midi

    s = _slot(slot, "kit")
    d = _device_helper()
    k = d.read_kit(s)

    info = d.tone_info(k.get(instrument, "tone"))
    natural = root or (getattr(info, "root", None) if info else None)
    if not natural:
        raise ToolError(
            f"{instrument}'s tone has no measured root, so there is no way to "
            f"know what it currently sounds at. Give `root`, or pick a tone "
            f"whose root the catalogue knows (tones.search).")

    want = note_to_midi(note)
    have = note_to_midi(natural)
    if want is None or have is None:
        raise ToolError("note and root must both be real notes, e.g. C1")

    # the tone is already offset by whatever TUNE currently holds
    current_shift = tune_semitones_for_byte(k.get(instrument, "tune") + 128)
    needed = (want - have)
    if abs(needed) > TUNE_SEMITONE_RANGE:
        raise ToolError(
            f"{note} is {needed:+d} semitones from {instrument}'s natural "
            f"{natural}; TUNE only reaches "
            f"+/-{TUNE_SEMITONE_RANGE:.0f}. Pick a tone rooted nearer, or a "
            f"note an octave closer.")

    byte, actual = tune_byte_for_semitones(needed)
    k.set(instrument, "tune", byte - 128)
    r = d.write_kit(s, k)
    r.update(instrument=instrument, note=note, natural_root=natural,
             semitones=round(actual, 2), requested_semitones=needed,
             tune_byte=byte, previous_semitones=round(current_shift, 2))
    if abs(actual - needed) > 0.05:
        r["note_"] = (f"the byte is a whole number, so this lands at "
                      f"{actual:+.2f} rather than {needed:+d} semitones")
    return r




@tool("kit.fix",
      "Act on what pattern.audit found, where the machine allows it. Smearing "
      "is fixable: an instrument whose tone rings for longer than the gap "
      "between its own hits gets its DECAY shortened to fit, using a curve "
      "measured off this machine (calibration.describe_decay). Level "
      "collisions are NOT fixable -- the faders own level -- so those come "
      "back as advice. Set apply=false to see the proposed changes first.",
      {"slot": {"type": ["integer", "string"], "description": "the PATTERN slot"},
       "variation": opt({"type": "string", "enum": list(VARIATIONS)}),
       "apply": opt({"type": "boolean", "description": "default true"}),
       "headroom": opt({"type": "number",
                        "description": "how much of the gap between hits a "
                                       "tone may fill, 0..1. Default 0.9 -- "
                                       "just short of the next hit."})})
def kit_fix(slot, variation="A", apply=True, headroom=0.9):
    from ..audit import audit
    from ..calibration import decay_byte_for_ms, decay_ms_for_byte

    s = _slot(slot)
    d = _device_helper()
    p = d.read_pattern(s)
    k = d.read_kit(p.kit)
    report = audit(p, k, d.catalog, variation=variation)

    changes, advice = [], []
    for f in report["findings"]:
        if f["kind"] != "smearing" or not f["instrument"]:
            advice.append({"kind": f["kind"], "detail": f["detail"],
                           "why_not_fixable": "not an envelope problem"})
            continue
        inst = f["instrument"]
        part = next((x for x in report["parts"] if x["instrument"] == inst), None)
        if part is None or part.get("melodic"):
            continue
        if part.get("decay_ms") is None:
            advice.append({
                "kind": "smearing", "instrument": inst, "detail": f["detail"],
                "why_not_fixable":
                    "the tone sustains rather than decaying, so shortening "
                    "DECAY will not stop it -- choose a different tone"})
            continue
        # the gap this part actually has to work with, at this tempo
        steps = p.get_steps(variation, inst)
        hits = [i for i, c in enumerate(steps) if c != "."]
        gaps = [b - a for a, b in zip(hits, hits[1:])]
        if not gaps:
            continue
        target_ms = min(gaps) * report["step_ms"] * float(headroom)
        current = k.get(inst, "decay")
        want = decay_byte_for_ms(target_ms)
        if want >= current:
            continue                    # already short enough
        changes.append({
            "instrument": inst, "from": current, "to": want,
            "from_ms": round(decay_ms_for_byte(current) or 0),
            "to_ms": round(decay_ms_for_byte(want) or 0),
            "target_ms": round(target_ms),
            "why": f"hits every {round(min(gaps) * report['step_ms'])} ms",
        })

    out = {"slot": s, "kit": p.kit, "kit_panel": p.kit + 1,
           "variation": variation, "verdict": report["verdict"],
           "changes": changes, "advice": advice, "applied": False}
    if apply and changes:
        for c in changes:
            k.set(c["instrument"], "decay", c["to"])
        d.write_kit(p.kit, k)
        out["applied"] = True
        out["note"] = ("DECAY was measured on one tone, so these are the right "
                       "shape rather than exact -- check by ear. history.undo "
                       "puts the kit back.")
    elif not changes:
        out["note"] = "nothing here is fixable by shortening a decay"
    return out




@tool("kit.balance",
      "Advisory loudness comparison across a kit's instruments, from measured "
      "tone peaks. Levels are owned by the physical faders and cannot be set "
      "from software, so this tells you which instrument will dominate -- it "
      "cannot fix it.",
      {"slot": {"type": ["integer", "string"]}})
def kit_balance(slot):
    s = _slot(slot, "kit")
    d = _device_helper()
    k = d.read_kit(s)
    cat = d.catalog
    rows, unknown = [], []
    for inst in TRACKS:
        tone = k.get(inst, "tone")
        info = cat.get(tone)
        if info and info.peak:
            rows.append({"instrument": inst, "tone": tone,
                         "name": info.name, "peak": info.peak,
                         "decay_ms": info.decay_ms, "sustained": info.sustained,
                         "centroid": info.centroid})
        else:
            unknown.append({"instrument": inst, "tone": tone,
                            "name": info.name if info else None})
    out = {"kit": k.name, "panel": s + 1, "measured": rows, "unmeasured": unknown}
    if len(rows) >= 2:
        import math
        loud = max(rows, key=lambda r: r["peak"])
        quiet = min(rows, key=lambda r: r["peak"])
        out["loudest"] = loud["instrument"]
        out["quietest"] = quiet["instrument"]
        if quiet["peak"] > 0:
            out["spread_db"] = round(20 * math.log10(loud["peak"] / quiet["peak"]), 1)
        # instruments sharing a frequency region will mask each other
        bright = [r for r in rows if r.get("centroid")]
        clashes = []
        for i, a in enumerate(bright):
            for b in bright[i + 1:]:
                if a["centroid"] and b["centroid"] and \
                        abs(a["centroid"] - b["centroid"]) < 120:
                    clashes.append(f"{a['instrument']} and {b['instrument']} "
                                   f"both sit near {a['centroid']} Hz")
        if clashes:
            out["possible_masking"] = clashes
    if unknown:
        out["note"] = ("some tones are not in the catalogue; run "
                       "`tr8s analyse-tones` to measure them")
    return out




@tool("kit.list", "Names of a range of kit slots.",
      {"lo": opt({"type": "integer"}), "hi": opt({"type": "integer"})})
def kit_list(lo=0, hi=15):
    d = _device_helper()
    out = []
    for s in range(lo, hi + 1):
        try:
            k = d.read_kit(s)
        except DeviceError:
            continue
        out.append({"slot": s, "panel": s + 1, "name": k.name})
    return out




@tool("kit.get", "Full contents of one kit: every instrument's tone and "
      "parameters.",
      {"slot": {"type": ["integer", "string"],
                "description": "0-based index; the panel shows this + 1"}})
def kit_get(slot):
    s = _slot(slot, "kit")
    dev = _device_helper()
    k = dev.read_kit(s)
    d = k.describe()
    d.update(slot=s, panel=s + 1)
    # resolve tone ids to names so a caller can see what a kit actually sounds
    # like without a second round of lookups
    for inst, fields in d["instruments"].items():
        info = dev.tone_info(fields["tone"])
        if info:
            fields["tone_name"] = info.name
            fields["tone_category"] = info.cat
            fields["melodic"] = info.type == 2
            if getattr(info, "root", None):
                fields["root"] = info.root
    return d




@tool("kit.set_instrument",
      "Change one instrument in a kit. 'level' cannot be set -- the physical "
      "fader owns it. Assigning a SAMPLE tone to an instrument that currently "
      "holds an ACB tone also needs inherit_from, or it will play near-silently.",
      {"slot": {"type": ["integer", "string"]},
       "instrument": {"type": "string", "enum": TRACKS},
       "tone": opt({"type": "integer", "minimum": 0, "maximum": 1023}),
       "tune": opt({"type": "integer", "minimum": -128, "maximum": 127}),
       "decay": opt({"type": "integer", "minimum": 0, "maximum": 255}),
       "pan": opt({"type": "integer", "minimum": -128, "maximum": 127}),
       "reverb": opt({"type": "integer", "minimum": 0, "maximum": 255}),
       "delay": opt({"type": "integer", "minimum": 0, "maximum": 255}),
       "lfo": opt({"type": "integer", "minimum": 0, "maximum": 255}),
       "inherit_from": opt({"type": "object",
                            "description": "{'kit': <slot>, 'instrument': 'LT'} "
                                           "- copy a working sample record first"})},
      mutates=True)
def kit_set_instrument(slot, instrument, tone=None, tune=None, decay=None,
                       pan=None, reverb=None, delay=None, lfo=None,
                       inherit_from=None, auto_donor=True):
    s = _slot(slot, "kit")
    d = _device_helper()
    k = d.read_kit(s)
    warnings = []
    if inherit_from:
        donor = d.read_kit(_slot(inherit_from["kit"], "kit"))
        k.inherit_record(instrument, donor, inherit_from.get("instrument", instrument))
    if tone is not None:
        info = d.catalog.get(tone) or d.read_tone(tone)
        if info and info.type == 2 and not k.has_sample_params(instrument):
            if auto_donor:
                donor = d.find_sample_donor(prefer_kit=s)
                if donor:
                    dk, dinst = donor
                    k.inherit_record(instrument, d.read_kit(dk) if dk != s else k,
                                     dinst)
                    warnings.append(
                        f"{instrument} had no sample parameters, so its record "
                        f"was inherited from kit {dk + 1}/{dinst} before "
                        f"assigning a sample tone")
                else:
                    warnings.append(
                        f"tone {tone} is a sample but no donor record with "
                        f"sample parameters was found; it will play "
                        f"near-silently")
            else:
                warnings.append(
                    f"tone {tone} '{info.name}' is a sample but {instrument}'s "
                    f"record has no sample parameters; it will play "
                    f"near-silently. Pass inherit_from or auto_donor.")
        k.set(instrument, "tone", tone)
    for f, v in (("tune", tune), ("decay", decay), ("pan", pan),
                 ("reverb", reverb), ("delay", delay), ("lfo", lfo)):
        if v is not None:
            k.set(instrument, f, v)
    r = d.write_kit(s, k)
    r["instrument"] = k.describe()["instruments"][instrument]
    r["warnings"] = warnings
    return r




@tool("kit.auto_build",
      "Choose a tone for every instrument using the MEASURED catalogue -- each "
      "tone's real pitch, decay, and brightness -- rather than by name. Picks a "
      "kick whose pitch belongs to the key so the bassline cannot beat against "
      "it, keeps parts off each other's brightness so nothing is masked, and "
      "gives the melodic tracks sustained sample tones that Coarse Tune can "
      "actually move. Set write=false to see the plan and the reason for every "
      "choice before anything is changed. IMPORTANT: committing a kit rewrites "
      "the kit reference of the last pattern that was transferred, so build "
      "every kit BEFORE writing the patterns that use them.",
      {"slot": {"type": ["integer", "string"]},
       "style": opt({"type": "string",
                     "description": "techno, hypnotic, dub, acid, hard, broken, "
                                    "dnb, lofi, house"}),
       "key": opt({"type": "string",
                   "description": "e.g. 'C minor', 'F# phrygian'. Techno lives "
                                  "in minor and phrygian."}),
       "melodic": opt({"type": "array", "items": {"type": "string"},
                       "description": "tracks to give melodic tones to, "
                                      "default LT and MT"}),
       "seed": opt({"type": "integer"}),
       "write": opt({"type": "boolean", "description": "default true"}),
       "name": opt({"type": "string"})}, mutates=True)
def kit_auto_build(slot, style="techno", key="C minor", melodic=None,
                   seed=None, write=True, name=None):
    from ..kitbuild import build
    d = _device_helper()
    try:
        plan = build(style, key, seed=seed, catalog=d.catalog,
                     melodic=tuple(melodic or ("LT", "MT")))
    except ValueError as e:
        raise ToolError(str(e)) from None
    if not write:
        plan["written"] = False
        return plan

    # one read and one write, not eleven of each: each round trip is about
    # two seconds over SysEx, which turns a kit into half a minute of waiting
    s = _slot(slot, "kit")
    warnings = []
    k = d.read_kit(s)
    donor_kit = None
    for inst, choice in plan["instruments"].items():
        info = d.catalog.get(choice["tone"])
        if info and info.type == 2 and not k.has_sample_params(inst):
            # a sample tone on a record with no envelope/gain fields plays
            # almost silently -- inherit one before assigning
            if donor_kit is None:
                found = d.find_sample_donor(prefer_kit=s)
                donor_kit = found or False
            if donor_kit:
                dk, dinst = donor_kit
                k.inherit_record(inst, d.read_kit(dk) if dk != s else k, dinst)
            else:
                warnings.append(
                    f"{inst}: no donor record with sample parameters was "
                    f"found, so '{choice['name']}' will play near-silently")
        try:
            k.set(inst, "tone", choice["tone"])
        except Exception as e:
            warnings.append(f"{inst}: {e}")
    if name:
        k.name = name
    d.write_kit(s, k)
    plan["written"] = True
    plan["slot"] = s
    plan["warnings"] = warnings
    plan["note"] = ("committing a kit re-points the last pattern that was "
                    "transferred at it (docs/PROTOCOL.md). Set pattern kit "
                    "references after the last kit is written, not before.")
    return plan




@tool("kit.create",
      "Build a new kit in a slot from a donor kit, optionally overriding "
      "instruments. Always base a kit on a real factory kit rather than an "
      "empty slot: empty slots hold ACB defaults whose sample-parameter bytes "
      "are zero.",
      {"slot": {"type": ["integer", "string"]},
       "name": {"type": "string"},
       "from_kit": {"type": ["integer", "string"],
                    "description": "donor kit slot to base this on"},
       "sample_donor": opt({"type": "object",
                            "description": "{'kit':<slot>,'instrument':'LT'} - a "
                                           "working sample instrument, copied "
                                           "into any instrument given a sample tone"}),
       "instruments": opt({"type": "object",
                           "description": "instrument -> {tone,tune,decay,pan,"
                                          "reverb,delay,lfo}"})},
      mutates=True)
def kit_create(slot, name, from_kit, sample_donor=None, instruments=None):
    s = _slot(slot, "kit")
    d = _device_helper()
    k = d.read_kit(_slot(from_kit, "kit")).copy()
    k.name = name
    warnings = []
    donor = None
    if sample_donor:
        donor = d.read_kit(_slot(sample_donor["kit"], "kit"))
        dinst = sample_donor.get("instrument", "LT")
    for inst, spec in (instruments or {}).items():
        tone = spec.get("tone")
        if tone is not None:
            info = d.catalog.get(tone)
            if info and info.type == 2:
                if donor is not None:
                    k.inherit_record(inst, donor, dinst)
                elif not k.has_sample_params(inst):
                    warnings.append(
                        f"{inst}: sample tone {tone} without a sample_donor; "
                        f"it will play near-silently")
        for f in ("tone", "tune", "decay", "pan", "reverb", "delay", "lfo"):
            if f in spec:
                k.set(inst, f, spec[f])
    r = d.write_kit(s, k)
    r["kit"] = k.describe()
    r["warnings"] = warnings
    return r


# ===================================================================== tones



@tool("kit.swap",
      "Change an instrument's sound by DESCRIPTION -- 'a darker kick', 'much "
      "shorter', 'brighter and longer' -- using the measured catalogue rather "
      "than names. Starts from what the instrument has now and moves along "
      "the named axes, staying in the same category. With apply=false it only "
      "lists candidates; with apply=true it assigns the best one. The player "
      "hears the change on the next hit.",
      {"slot": {"type": ["integer", "string"], "description": "the KIT slot"},
       "instrument": {"type": "string", "enum": TRACKS},
       "description": {"type": "string",
                       "description": "darker/brighter, shorter/longer, "
                                      "lower/higher, louder/quieter, with "
                                      "'a bit' / 'much' for the amount"},
       "apply": opt({"type": "boolean", "description": "default true"}),
       "pick": opt({"type": "integer", "minimum": 0,
                    "description": "which candidate to apply, default 0 (best)"}),
       "same_category": opt({"type": "boolean", "description": "default true"})},
      mutates=True)
def kit_swap(slot, instrument, description, apply=True, pick=0,
             same_category=True):
    from ..swap import by_description
    d = _device_helper()
    s = _slot(slot, "kit")
    k = d.read_kit(s)
    cur = k.get(instrument, "tone")
    r = by_description(d.catalog, cur, description, same_category=same_category)
    if "error" in r:
        raise ToolError(r["error"])
    r["instrument"] = instrument
    if not apply or not r["candidates"]:
        r["applied"] = False
        return r
    choice = r["candidates"][min(int(pick), len(r["candidates"]) - 1)]
    res = kit_set_instrument(s, instrument, tone=choice["tone"])
    r["applied"] = True
    r["chosen"] = choice
    r["warnings"] = res.get("warnings") or []
    return r


@tool("kit.neighbours",
      "The tones most like the one an instrument has now, nearest first, by "
      "measured similarity (brightness, decay, pitch, loudness). This is what "
      "the studio's swap arrows step through; use it to offer 'something like "
      "this but different'.",
      {"slot": {"type": ["integer", "string"]},
       "instrument": {"type": "string", "enum": TRACKS},
       "limit": opt({"type": "integer", "minimum": 1, "maximum": 40}),
       "same_category": opt({"type": "boolean"})})
def kit_neighbours(slot, instrument, limit=12, same_category=True):
    from ..swap import _brief, neighbours
    d = _device_helper()
    k = d.read_kit(_slot(slot, "kit"))
    cur = k.get(instrument, "tone")
    info = d.catalog.get(cur)
    return {"instrument": instrument,
            "current": _brief(info) if info else {"tone": cur},
            "neighbours": [_brief(t) for t in
                           neighbours(d.catalog, cur, limit, same_category)]}


@tool("sample.import",
      "Put a WAV file on the machine as a new user tone, then (optionally) "
      "assign it to an instrument. Any PCM WAV: it is resampled to 44.1 kHz, "
      "mixed to mono and scaled to 16 bits, which is the machine's own "
      "format. Refuses before sending anything if it will not fit. Returns "
      "the new tone id (624..1023).",
      {"path": {"type": "string", "description": "a .wav file on this computer"},
       "name": opt({"type": "string", "description": "up to 16 characters; "
                                                     "defaults to the filename"}),
       "assign_to": opt({"type": "string", "enum": TRACKS,
                         "description": "instrument to put it on"}),
       "slot": opt({"type": ["integer", "string"],
                    "description": "kit slot, needed with assign_to"}),
       "reuse_tone": opt({"type": "integer", "minimum": 624, "maximum": 1023,
                          "description": "overwrite this user tone's own "
                                         "sample memory instead of taking new "
                                         "space. The only way to recycle "
                                         "memory on this firmware."})},
      mutates=True)
def sample_import(path, name=None, assign_to=None, slot=None, reuse_tone=None):
    from ..samples import SampleError, import_sample
    d = _device_helper()
    try:
        r = import_sample(d.transport, path, name=name, reuse_tone=reuse_tone)
    except SampleError as e:
        raise ToolError(str(e)) from None
    except (OSError, wave.Error) as e:
        raise ToolError(f"could not read {path}: {e}") from None
    # the machine has a new name at this id; make the studio agree everywhere
    d._tone_cache.pop(r["tone"], None)
    try:
        fresh = d.read_tone(r["tone"])
        if fresh is not None:
            d.catalog.put(fresh)
    except Exception:
        pass
    if assign_to:
        if slot is None:
            raise ToolError("assign_to needs the kit slot too")
        res = kit_set_instrument(_slot(slot, "kit"), assign_to, tone=r["tone"])
        r["assigned"] = assign_to
        r["warnings"] = res.get("warnings") or []
    r["note"] = ("the new tone is not in the measured catalogue yet, so "
                 "kit.swap and kit.neighbours cannot see it until "
                 "analyse-tones runs again")
    return r


@tool("sample.space",
      "How much sample memory is free on the machine, and the longest run a "
      "single sample can occupy.",
      {})
def sample_space():
    fa = _device_helper().transport.free_area()
    return {**fa, "total_free_mb": round(fa["total_free"] / 1e6, 2),
            "longest_free_mb": round(fa["longest_free"] / 1e6, 2),
            "free_tone_slots": _device_helper().transport.free_tone_count()
            if hasattr(_device_helper().transport, "free_tone_count") else None}


@tool("sample.fetch",
      "Download a WAV from a URL and put it on the machine as a user tone -- "
      "the AI's way to change a sound to anything on the internet. The file "
      "is kept under the data directory so it can be re-imported without "
      "downloading again. Same conversion and same rules as sample.import; "
      "give reuse_tone to recycle a slot, since sample memory cannot be "
      "freed on this firmware.",
      {"url": {"type": "string", "description": "an http(s) URL to a .wav"},
       "name": opt({"type": "string", "description": "tone name, <= 16 chars"}),
       "assign_to": opt({"type": "string", "enum": TRACKS}),
       "slot": opt({"type": ["integer", "string"]}),
       "reuse_tone": opt({"type": "integer", "minimum": 624, "maximum": 1023}),
       "max_mb": opt({"type": "number", "description": "refuse larger downloads; default 8"})},
      mutates=True)
def sample_fetch(url, name=None, assign_to=None, slot=None, reuse_tone=None,
                 max_mb=8.0):
    import hashlib
    import urllib.request
    from urllib.parse import urlparse
    if not str(url).lower().startswith(("http://", "https://")):
        raise ToolError("only http(s) URLs are fetched")
    dest_dir = config.data_dir() / "samples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(urlparse(url).path).stem or "sample"
    dest = dest_dir / f"{stem}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.wav"
    if not dest.is_file():
        req = urllib.request.Request(url, headers={"User-Agent": "tr8s-studio/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                data = r.read(int(max_mb * 1e6) + 1)
        except Exception as e:
            raise ToolError(f"could not download {url}: {e}") from None
        if len(data) > max_mb * 1e6:
            raise ToolError(f"{url} is larger than {max_mb} MB; raise max_mb if you mean it")
        if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
            raise ToolError(
                f"{url} is not a WAV (content-type {ctype or 'unknown'}, "
                f"starts {data[:4]!r}). Only PCM WAV can go on the machine.")
        dest.write_bytes(data)
    r = sample_import(str(dest), name=name or stem[:16], assign_to=assign_to,
                      slot=slot, reuse_tone=reuse_tone)
    r["source"] = url
    r["file"] = str(dest)
    return r
