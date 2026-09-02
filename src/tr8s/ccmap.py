"""
What every Control Change from the TR-8S means.

Taken from the MIDI Implementation Chart (v1.10), which names each transmitted
controller -- a column that only survives when the PDF is extracted with its
layout kept, which is why it went unread for so long. Verified live: with
UTILITY:MIDI:Tx EditData ON, moving a panel control sends exactly these.

Every value is 0..127. TUNE is centred at 64.
"""

from __future__ import annotations

INSTRUMENT_CC = {
    #      TUNE  DECAY  LEVEL  CTRL
    "BD": (20,   23,    24,    96),
    "SD": (25,   28,    29,    97),
    "LT": (46,   47,    48,    102),
    "MT": (49,   50,    51,    103),
    "HT": (52,   53,    54,    104),
    "RS": (55,   56,    57,    105),
    "HC": (58,   59,    60,    106),
    "CH": (61,   62,    63,    107),
    "OH": (80,   81,    82,    108),
    "CC": (83,   84,    85,    109),
    "RC": (86,   87,    88,    110),
}
PARAMS = ("tune", "decay", "level", "ctrl")

MASTER_CC = {
    9: "shuffle",
    12: "ext_in_level",
    14: "auto_fill_on",         # only with LocalSw = SURFACE
    15: "master_fx_on",
    16: "delay_level",
    17: "delay_time",
    18: "delay_feedback",
    19: "master_fx_ctrl",
    70: "manual_trig",          # only with LocalSw = SURFACE
    71: "accent",
    91: "reverb_level",
}

# the beat counter the machine sends while playing; not a control at all
BEAT_CC = 2

# cc -> (instrument, param) or (None, master name)
_BY_CC: dict[int, tuple] = {}
for _inst, _ccs in INSTRUMENT_CC.items():
    for _p, _cc in zip(PARAMS, _ccs):
        _BY_CC[_cc] = (_inst, _p)
for _cc, _name in MASTER_CC.items():
    _BY_CC[_cc] = (None, _name)


def describe(cc: int) -> tuple | None:
    """(instrument, param) for a strip control, (None, name) for a master one,
    None for anything unmapped."""
    return _BY_CC.get(cc)


def label(cc: int) -> str:
    d = describe(cc)
    if d is None:
        return "beat" if cc == BEAT_CC else f"CC {cc}"
    inst, param = d
    return f"{inst} {param.upper()}" if inst else param.replace("_", " ")


def cc_for(inst: str, param: str) -> int:
    return INSTRUMENT_CC[inst][PARAMS.index(param)]


def to_kit_value(param: str, cc_value: int) -> int:
    """
    A CC is 7-bit; the kit stores 8-bit. TUNE and PAN are signed in the kit
    model (-128..127, centre 0); the CC is 0..127 with centre 64.
    """
    v = max(0, min(127, int(cc_value)))
    if param == "tune":
        return (v - 64) * 2
    return v * 2 + (1 if v == 127 else 0)


def from_kit_value(param: str, kit_value: int) -> int:
    if param == "tune":
        return max(0, min(127, kit_value // 2 + 64))
    return max(0, min(127, kit_value // 2))
