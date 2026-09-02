"""track tools — see the package docstring for the conventions."""

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
from .kit import kit_auto_build
from .pattern import pattern_arrange, pattern_audit, pattern_set_header, pattern_set_line

@tool("track.create",
      "Make a complete track in one call: a kit chosen from the measured tone "
      "catalogue, all eight variations arranged as intro / main / fill / break "
      "/ drop / peak, a bassline in key, and a mix audit of the result. This "
      "is the fast path -- prefer it over calling kit.auto_build, "
      "pattern.arrange and pattern.set_line separately, which also risks the "
      "kit-reference trap (docs/PROTOCOL.md). Everything is seeded and the "
      "seed is returned, so a track that worked can be rebuilt or varied.",
      {"slot": {"type": ["integer", "string"],
                "description": "pattern slot to write, e.g. '8-12'"},
       "style": {"type": "string",
                 "description": "techno, hypnotic, dub, acid, hard, broken, "
                                "dnb, lofi, house -- see styles.list"},
       "name": opt({"type": "string", "description": "up to 8 characters"}),
       "key": opt({"type": "string",
                   "description": "e.g. 'C minor', 'F# phrygian'. Defaults to "
                                  "one that suits the style."}),
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "kit_slot": opt({"type": ["integer", "string"],
                        "description": "kit slot to build. OMIT to leave the "
                                       "kit alone and use whatever the pattern "
                                       "already points at -- passing a slot "
                                       "OVERWRITES that kit."}),
       "line": opt({"type": "string", "enum": ["bass", "acid", "stab", "arp",
                                               "none"]}),
       "melodic_track": opt({"type": "string", "enum": TRACKS}),
       "seed": opt({"type": "integer"}),
       "set_tempo": opt({"type": "boolean"})}, mutates=True)
def track_create(slot, style, name=None, key=None, energy=0.7, kit_slot=None,
                 line=None, melodic_track="LT", seed=None, set_tempo=True):
    import random as _random
    from ..style import STYLES

    if style not in STYLES:
        raise ToolError(f"unknown style {style!r}; have {', '.join(STYLES)}")
    s = _slot(slot)
    key = key or DEFAULT_KEYS.get(style, "C minor")
    line = line or DEFAULT_LINE.get(style, "bass")
    if seed is None:
        seed = _random.randrange(1 << 30)
    name = (name or style.upper())[:8]
    out = {"slot": s, "panel": slot_to_panel(s), "style": style, "key": key,
           "energy": energy, "seed": seed, "name": name, "steps": []}

    # 1. the kit FIRST and completely. Committing a kit re-points the last
    #    pattern transferred at it, so no pattern may be written until every
    #    kit commit is done.
    if kit_slot is not None:
        plan = kit_auto_build(kit_slot, style=style, key=key, name=name,
                              seed=seed)
        out["kit"] = {"slot": plan["slot"],
                      "instruments": {k: {"tone": v["tone"], "name": v["name"],
                                          "root": v["root"], "why": v["why"]}
                                      for k, v in plan["instruments"].items()},
                      "warnings": plan.get("warnings") or []}
        out["steps"].append(f"built kit {plan['slot'] + 1} from the catalogue")

    # 2. the arrangement
    arr = pattern_arrange(s, style=style, energy=energy, seed=seed, name=name,
                          set_tempo=set_tempo)
    out["tempo"] = arr["tempo"]
    out["roles"] = arr["roles"]
    out["steps"].append("arranged A-H as intro / main / fill / break / peak")

    # 3. point the pattern at its kit, now that no more kits will be committed
    if kit_slot is not None:
        pattern_set_header(s, kit=_slot(kit_slot, "kit"))
        out["steps"].append(f"pointed the pattern at kit {_slot(kit_slot, 'kit') + 1}")

    # 4. the line, on the variations that carry the groove
    if line != "none":
        written, warnings = [], []
        for v in ("B", "C", "G"):
            try:
                r = pattern_set_line(s, v, melodic_track, line, key=key,
                                     energy=energy, seed=seed + ord(v))
                written.append({"variation": v, "notes": r["notes"]})
                warnings.extend(r.get("warnings") or [])
                out["root"] = r["root"]
                out["panel_setup"] = r["panel_setup"]
            except ToolError as e:
                out["line_error"] = str(e)
                break
        if written:
            out["line"] = {"shape": line, "instrument": melodic_track,
                           "variations": written, "warnings": warnings}
            out["steps"].append(f"wrote a {line} line on {melodic_track}")

    # 5. say what is wrong with it
    try:
        out["audit"] = pattern_audit(s, variation="C")
        out["steps"].append("audited the main variation")
    except ToolError as e:
        out["audit"] = {"error": str(e)}
    return out




@tool("track.remix",
      "Rework a track that already exists: same idea, different roll of the "
      "dice. Keeps the kit, the key and the tempo, and rewrites the "
      "arrangement and the line from a new seed. Use it for 'another one like "
      "that' and for 'same but harder' -- pass a new energy to change the "
      "intensity while keeping the seed, or a new seed to change the pattern "
      "while keeping the intensity.",
      {"slot": {"type": ["integer", "string"]},
       "style": {"type": "string"},
       "into": opt({"type": ["integer", "string"],
                    "description": "write the result here instead, leaving the "
                                   "original alone. STRONGLY preferred."}),
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "key": opt({"type": "string"}),
       "seed": opt({"type": "integer"}),
       "line": opt({"type": "string",
                    "enum": ["bass", "acid", "stab", "arp", "none", "keep"]}),
       "melodic_track": opt({"type": "string", "enum": TRACKS}),
       "name": opt({"type": "string"})}, mutates=True)
def track_remix(slot, style, into=None, energy=None, key=None, seed=None,
                line=None, melodic_track="LT", name=None):
    import random as _random
    src = _slot(slot)
    dst = _slot(into) if into is not None else src
    d = _device_helper()
    original = d.read_pattern(src)

    if seed is None:
        seed = _random.randrange(1 << 30)
    if energy is None:
        energy = 0.7
    if line == "keep":
        line = None

    if dst != src:
        # carry the original's kit and tempo across, then rebuild on top
        p = d.read_pattern(dst)
        p.kit = original.kit
        p.tempo = original.tempo
        p.scale = original.scale
        d.write_pattern(dst, p)

    out = track_create(dst, style, name=name or original.name,
                       key=key, energy=energy, kit_slot=None,
                       line=line, melodic_track=melodic_track, seed=seed,
                       set_tempo=False)
    out["remixed_from"] = {"slot": src, "panel": slot_to_panel(src),
                           "name": original.name}
    out["kept"] = {"kit": original.kit + 1, "tempo": original.tempo}
    if dst == src:
        out["warning"] = ("the original was overwritten -- pass `into` next "
                          "time to keep both. history.undo puts it back.")
    return out


