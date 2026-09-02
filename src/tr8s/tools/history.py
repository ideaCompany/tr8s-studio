"""history tools — see the package docstring for the conventions."""

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

@tool("history.list",
      "What can be undone. Every mutating tool snapshots the slot it is about "
      "to change, so an edit that went wrong can be stepped back.",
      {"limit": opt({"type": "integer", "minimum": 1, "maximum": 64})})
def history_list(limit=20):
    return {"undo": HISTORY.entries(limit), "redo": HISTORY.redo_entries(limit),
            "depth": len(HISTORY),
            "note": "history only covers writes made through these tools; "
                    "changes made on the panel are invisible to it"}




@tool("history.undo",
      "Put back what the last mutating tool overwrote. Repeat to keep stepping "
      "back. The machine itself has no undo -- this restores a snapshot taken "
      "before the change.",
      {"steps": opt({"type": "integer", "minimum": 1, "maximum": 32})},
      mutates=True)
def history_undo(steps=1):
    d = _device_helper()
    done = []
    for _ in range(max(1, int(steps))):
        try:
            done.append(HISTORY.undo(d))
        except LookupError as e:
            if not done:
                raise ToolError(str(e)) from None
            break
    return {"undone": done, "remaining": len(HISTORY)}




@tool("history.redo", "Re-apply what was just undone.",
      {"steps": opt({"type": "integer", "minimum": 1, "maximum": 32})},
      mutates=True)
def history_redo(steps=1):
    d = _device_helper()
    done = []
    for _ in range(max(1, int(steps))):
        try:
            done.append(HISTORY.redo(d))
        except LookupError as e:
            if not done:
                raise ToolError(str(e)) from None
            break
    return {"redone": done}
