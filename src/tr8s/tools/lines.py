"""lines tools — see the package docstring for the conventions."""

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

@tool("lines.preview",
      "Generate a bassline, acid line, stab or arpeggio in a key WITHOUT "
      "writing it. Use this to audition a few seeds before committing one.",
      {"shape": {"type": "string", "enum": ["bass", "acid", "stab", "arp"]},
       "key": opt({"type": "string", "description": "e.g. 'C minor', 'F# phrygian'"}),
       "energy": opt({"type": "number", "minimum": 0, "maximum": 1}),
       "root": opt({"type": "string",
                    "description": "the tone's natural pitch. Defaults to C2."}),
       "seed": opt({"type": "integer"})})
def lines_preview(shape, key="C minor", energy=0.6, root="C2", seed=None):
    from ..lines import generate as gen
    try:
        return gen(shape, key=key, energy=energy, root=root, seed=seed)
    except ValueError as e:
        raise ToolError(str(e)) from None


