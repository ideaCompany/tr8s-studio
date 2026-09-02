"""tones tools — see the package docstring for the conventions."""

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

@tool("tones.search",
      "Find tones by measured properties, not just names. Use this to pick "
      "sounds: 'root' is what a tone actually sounds at, 'decay_ms' separates "
      "stabs from pads, 'centroid' is brightness in Hz.",
      {"category": opt({"type": "string",
                        "description": "BASS, SYNTH1, SYNTH2, SCALED, CHORD, "
                                       "BD, SD, ... (comma-separated for several)"}),
       "melodic": opt({"type": "boolean",
                       "description": "true = sample tones only, the only ones "
                                      "that can play melodies"}),
       "root": opt({"type": "string", "description": "pitch class, e.g. 'C'"}),
       "near_hz": opt({"type": "number", "description": "sort by closeness to this"}),
       "max_decay_ms": opt({"type": "integer"}),
       "min_decay_ms": opt({"type": "integer"}),
       "brighter_than": opt({"type": "integer"}),
       "darker_than": opt({"type": "integer"}),
       "name_contains": opt({"type": "string"}),
       "limit": opt({"type": "integer"})})
def tones_search(**kw):
    cat = Catalog.load()
    if not len(cat):
        raise ToolError(
            "the tone catalogue is empty. Run `tr8s analyse-tones` to measure "
            "them, or use tones.probe for a single tone's name and type.")
    return [vars(t) for t in cat.search(**kw)]




@tool("tones.get", "Everything known about one tone, measured and metadata.",
      {"tone": {"type": "integer", "minimum": 0, "maximum": 1023}})
def tones_get(tone: int):
    cat = Catalog.load()
    t = cat.get(tone)
    if t:
        return vars(t)
    live = _device_helper().read_tone(tone)
    if not live:
        raise ToolError(f"no tone {tone}")
    d = vars(live)
    d["note"] = "not in the catalogue; only name/category/type are known"
    return d




@tool("tones.probe", "Read a tone's name, category and type straight from the "
      "device, without the catalogue.",
      {"tone": {"type": "integer", "minimum": 0, "maximum": 1023}})
def tones_probe(tone: int):
    t = _device_helper().read_tone(tone)
    if not t:
        raise ToolError(f"no tone {tone}")
    return vars(t)


# ====================================================================== audio

