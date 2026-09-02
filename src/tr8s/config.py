"""
Runtime configuration. No paths are hardcoded to any one machine.

Resolution order for the data directory (backups, tone catalogue, templates):

    1. $TR8S_DATA
    2. $XDG_DATA_HOME/tr8s
    3. ~/.local/share/tr8s

The MIDI device can be overridden with $TR8S_PORT; otherwise the first Roland
TR-8S rawmidi node is discovered automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "tr8s"


def data_dir() -> Path:
    env = os.environ.get("TR8S_DATA")
    if env:
        p = Path(env).expanduser()
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        p = base / APP
    p.mkdir(parents=True, exist_ok=True)
    return p


def subdir(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def patterns_dir() -> Path:
    return subdir("backups/patterns")


def kits_dir() -> Path:
    return subdir("backups/kits")


def tone_catalog_path() -> Path:
    return data_dir() / "tones.json"


def template_path() -> Path:
    """An empty-slot pattern blob, used as the base when authoring."""
    return data_dir() / "template_pattern.bin"


def settings_path() -> Path:
    return data_dir() / "studio.json"


def load_settings() -> dict:
    """
    Things the studio worked out about this machine and should not have to
    work out again -- which MIDI channel carries the pattern, for instance.
    """
    import json
    p = settings_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return {}


def save_settings(values: dict):
    import json
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        current = load_settings()
        current.update(values)
        p.write_text(json.dumps(current, indent=1))
    except OSError:
        pass                    # a settings file we cannot write is not fatal


def find_port() -> str:
    """Locate the TR-8S rawmidi device node."""
    env = os.environ.get("TR8S_PORT")
    if env:
        return env
    # /proc/asound/cardN/midiM names the device; match the TR-8S
    for card in sorted(Path("/proc/asound").glob("card*")):
        for midi in sorted(card.glob("midi*")):
            try:
                if "TR-8S" in midi.read_text():
                    n = card.name.replace("card", "")
                    d = midi.name.replace("midi", "")
                    node = Path(f"/dev/snd/midiC{n}D{d}")
                    if node.exists():
                        return str(node)
            except OSError:
                continue
    for node in sorted(Path("/dev/snd").glob("midiC*D*")):
        return str(node)
    raise RuntimeError(
        "no TR-8S MIDI device found. Is it connected and powered on? "
        "Override with TR8S_PORT=/dev/snd/midiCxDy"
    )


def find_audio_device() -> str:
    """ALSA capture device for the TR-8S's own audio stream."""
    env = os.environ.get("TR8S_AUDIO")
    if env:
        return env
    try:
        cards = Path("/proc/asound/cards").read_text()
    except OSError:
        return "hw:1,0"
    for line in cards.splitlines():
        if "TR-8S" in line or "TR8S" in line:
            num = line.strip().split()[0]
            return f"hw:{num},0"
    return "hw:1,0"
