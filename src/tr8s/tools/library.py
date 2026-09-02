"""library tools — see the package docstring for the conventions."""

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
from .pattern import pattern_import

@tool("library.list",
      "The finished tracks kept as JSON in the repo, with the style, key and "
      "tempo of each. These are known-good starting points -- loading one is "
      "usually better than generating from scratch when the user asks for "
      "something that already exists here.",
      {})
def library_list():
    import json as _json
    out = []
    d = _library_dir()
    if not d.is_dir():
        return {"tracks": [], "note": f"no library directory at {d}"}
    for f in sorted(d.glob("*.json")):
        try:
            doc = _json.loads(f.read_text())
        except Exception as e:
            out.append({"name": f.stem, "error": str(e)})
            continue
        meta = doc.get("_meta") or {}
        out.append({"name": f.stem, "title": doc.get("name"),
                    "tempo": doc.get("tempo"), "style": meta.get("style"),
                    "key": meta.get("key"), "about": meta.get("about"),
                    "variations": sorted(doc.get("variations") or {})})
    return {"tracks": out, "directory": str(d)}




@tool("library.load",
      "Write one of the library tracks into a pattern slot. Reports what was "
      "in the slot beforehand, since this overwrites it -- history.undo puts "
      "it back.",
      {"name": {"type": "string", "description": "from library.list, e.g. 'acidtrax'"},
       "slot": {"type": ["integer", "string"]},
       "commit": opt({"type": "boolean"})}, mutates=True)
def library_load(name, slot, commit=True):
    import json as _json
    f = _library_dir() / f"{str(name).strip().lower()}.json"
    if not f.is_file():
        have = sorted(p.stem for p in _library_dir().glob("*.json"))
        raise ToolError(f"no library track {name!r}; have {', '.join(have)}")
    doc = _json.loads(f.read_text())

    s = _slot(slot)
    try:
        was = _device_helper().read_pattern(s).name
    except DeviceError:
        was = None

    r = pattern_import(s, doc, commit=commit)
    r.update(loaded=name, title=doc.get("name"), replaced=was,
             meta=doc.get("_meta") or {})
    if doc.get("variations"):
        r["panel_setup"] = [
            "MOTION [ON] must be lit for the melodies to sound",
            "Coarse Tune must be on the melodic instrument's CTRL knob",
            f"the track expects kit {doc.get('kit', 0) + 1}",
        ]
    return r


