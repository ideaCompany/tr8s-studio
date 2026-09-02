"""styles tools — see the package docstring for the conventions."""

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

@tool("styles.list",
      "The groove styles the generator knows, with their tempo ranges and what "
      "each one is. Read this before generating, so the style asked for is one "
      "that exists rather than the closest guess.",
      {})
def styles_list():
    from ..style import ROLES, describe
    return {"styles": describe(), "roles": list(ROLES),
            "energy": "0..1. Layers enter in a producer's order as it rises: "
                      "open hat, then 16th hats, then ride, then ghost notes."}


