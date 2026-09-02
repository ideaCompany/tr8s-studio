"""
tr8s — drive a Roland TR-8S over USB: patterns, kits, melodies.

Layers, lowest first:

    config      paths and device discovery, no hardcoded machine specifics
    transport   SysEx framing and bulk transfer; moves opaque blobs
    pattern     the 24504-byte pattern model: steps, motion, header
    kit         the 1312-byte kit model: tones and per-instrument parameters
    melody      note names <-> per-step tune motion
    tones       the measured tone catalogue (roots, loudness, decay, brightness)
    device      the facade: one object speaking Patterns, Kits and Tones
    tools       a named, JSON-schema'd command surface for an LLM or a CLI

Typical use:

    from tr8s.tools import call, schemas
    call("tones.search", {"category": "BASS", "melodic": True})
    call("pattern.set_melody", {"slot": "8-07", "variation": "C",
                                "instrument": "LT",
                                "notes": "C2 . G2 C3", "root": "C2"})

The protocol and every measured constant are documented in docs/PROTOCOL.md.
"""

__version__ = "0.1.0"

from .device import Device, panel_to_slot, slot_to_panel  # noqa: F401
from .kit import Kit  # noqa: F401
from .pattern import Pattern  # noqa: F401
from .tones import Catalog  # noqa: F401

__all__ = ["Device", "Kit", "Pattern", "Catalog",
           "panel_to_slot", "slot_to_panel", "__version__"]
