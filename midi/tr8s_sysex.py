#!/usr/bin/env python3
"""
TR-8S SysEx client.

Wire format reconstructed from Roland's own AIRA web-client JavaScript
(github.com/compuphonic/TR-8S-SysEx, js/Com/MidiManager.js + js/Tr8s/*):

    F0 41 <devId> 00 00 00 45 <cmd> <addr x4> <data...> <checksum> F7
    cmd: 0x12 = DT1 (data set), 0x11 = RQ1 (data request)
    checksum = 127 & (128 - (127 & sum(addr + data)))

Addresses come from the base64 config blob in Tr8sData.js:

    utility base        50 00 00 00
      command.version   +0x13     command.uid      +0x14
      command.playing   +0x10     command.lock     +0x11
      get.pattern       +0x41     send.pattern     +0x40
      write.pattern     +0x01     (under offsets.write)
    temp.ptn.name       20 00 00 00, block 10 00 00, 16 bytes
    temp.stp.currentPattern  01 00 00 01, 1 byte

Pattern blob is 24504 bytes, chunk id "PTN ".

SAFETY: only read-only operations are implemented here (version, uid,
pattern names). Nothing in this file writes to the TR-8S's memory.
"""

import os
import sys
import time

ROLAND = 0x41
MODEL_TR8S = [0x00, 0x00, 0x00, 0x45]
DT1 = 0x12
RQ1 = 0x11

DEV_DEFAULT = 0x10

UTILITY_ADDR = [0x50, 0x00, 0x00, 0x00]
CMD_OFFSETS = {
    "playing": 0x10, "lock": 0x11, "display": 0x12,
    "version": 0x13, "uid": 0x14,
    "optimize": 0x20, "freeArea": 0x21,
    "freeToneCount": 0x22, "freeTone": 0x23, "deleteTone": 0x24,
}
PTN_NAME_ADDR = [0x20, 0x00, 0x00, 0x00]
PTN_NAME_BLOCK = [0x10, 0x00, 0x00]

PORTS = ["/dev/snd/midiC1D1", "/dev/snd/midiC1D0"]  # CTRL port first


# ---------------------------------------------------------------- helpers

def decode7(addr):
    v = 0
    for b in addr:
        v = (v << 7) | (b & 0x7F)
    return v


def encode7(value, nbytes):
    out = [0] * nbytes
    for i in range(nbytes - 1, -1, -1):
        out[i] = value & 0x7F
        value >>= 7
    return out


def offset_address(addr, offset, mult=1):
    return encode7(decode7(addr) + offset * mult, len(addr))


def checksum(payload):
    return 127 & (128 - (127 & sum(payload)))


def make_sysex(cmd, addr, data, dev=DEV_DEFAULT):
    payload = list(addr) + list(data)
    return bytes([0xF0, ROLAND, dev] + MODEL_TR8S + [cmd]
                 + payload + [checksum(payload), 0xF7])


def parse_sysex(buf):
    """Split a byte buffer into complete SysEx messages."""
    msgs, cur, inside = [], [], False
    for b in buf:
        if b == 0xF0:
            inside, cur = True, [b]
        elif inside:
            cur.append(b)
            if b == 0xF7:
                msgs.append(bytes(cur))
                inside = False
    return msgs


def describe(msg):
    if len(msg) < 12 or msg[1] != ROLAND:
        return f"(non-Roland or short: {msg[:8].hex(' ')})"
    dev, cmd = msg[2], msg[7]
    addr = msg[8:12]
    data = msg[12:-2]
    name = {DT1: "DT1", RQ1: "RQ1"}.get(cmd, f"cmd{cmd:02X}")
    return (f"{name} dev=0x{dev:02X} addr={addr.hex(' ')} "
            f"len={len(data)} data={data[:24].hex(' ')}"
            + ("..." if len(data) > 24 else ""))


# ---------------------------------------------------------------- transport

class Port:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR)
        os.set_blocking(self.fd, False)

    def drain(self):
        try:
            while os.read(self.fd, 4096):
                pass
        except BlockingIOError:
            pass

    def send(self, msg):
        os.write(self.fd, msg)

    def collect(self, seconds=1.5, hard_cap=20.0):
        """
        Gather non-realtime bytes. The TR-8S streams clock (0xF8) and active
        sensing (0xFE) continuously, so those must be discarded BEFORE deciding
        whether data is still arriving -- otherwise the idle timer never expires.
        """
        buf = bytearray()
        t0 = time.time()
        start = time.time()
        while time.time() - t0 < seconds and time.time() - start < hard_cap:
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            useful = bytes(b for b in chunk if b < 0xF8)
            if useful:
                buf += useful
                t0 = time.time()  # extend only on real (non-realtime) data
        return bytes(buf)

    def close(self):
        os.close(self.fd)


def request(port, addr, data=(0,), dev=DEV_DEFAULT, wait=1.5, cmd=DT1):
    port.drain()
    msg = make_sysex(cmd, addr, data, dev)
    port.send(msg)
    return parse_sysex(port.collect(wait)), msg


# ---------------------------------------------------------------- commands

def cmd_probe():
    """Try every port/device-id combination with a harmless version query."""
    addr = offset_address(UTILITY_ADDR, CMD_OFFSETS["version"])
    print(f"version address: {' '.join(f'{b:02X}' for b in addr)}")
    found = False
    for path in PORTS:
        if not os.path.exists(path):
            print(f"{path}: absent")
            continue
        try:
            p = Port(path)
        except OSError as e:
            print(f"{path}: {e}")
            continue
        for dev in (0x10, 0x00, 0x7F):
            msgs, sent = request(p, addr, [0], dev, wait=1.2)
            tag = f"{path} dev=0x{dev:02X}"
            if msgs:
                found = True
                print(f"\n*** REPLY on {tag}")
                print(f"    sent: {sent.hex(' ')}")
                for m in msgs:
                    print(f"    recv: {describe(m)}")
                    body = m[12:-2]
                    txt = "".join(chr(c) for c in body if 32 <= c < 127)
                    if txt.strip():
                        print(f"    text: {txt!r}")
            else:
                print(f"{tag}: no reply")
        p.close()
    if not found:
        print("\nNo SysEx replies. Possible causes:")
        print(" - the TR-8S 'SysEx ID' utility setting differs from those tried")
        print(" - the unit needs Rx SysEx enabled")
        print(" - the CTRL port is not exposed as a rawmidi device on Linux")
    return found


def cmd_raw(addr_hex, data_hex="00", dev=DEV_DEFAULT, port=None):
    addr = [int(x, 16) for x in addr_hex.split()]
    data = [int(x, 16) for x in data_hex.split()] if data_hex else [0]
    paths = [port] if port else PORTS
    for path in paths:
        if not os.path.exists(path):
            continue
        p = Port(path)
        msgs, sent = request(p, addr, data, dev)
        print(f"{path}: sent {sent.hex(' ')}")
        for m in msgs:
            print(f"   recv: {describe(m)}")
        if not msgs:
            print("   (no reply)")
        p.close()


GET_OFFSETS = {"system": 0x31, "pattern": 0x41, "kit": 0x51,
               "tone": 0x61, "pcmTone": 0x71, "sample": 0x73}
BLOB_SIZE = {"system": 752, "pattern": 24504, "kit": 1312,
             "tone": 36, "pcmTone": 64}
# offsets.data: chunk-size -> 2-byte offset, plus a progress channel
DATA_OFFSETS = {1: [1, 0], 2: [1, 1], 4: [1, 2], 8: [1, 3], 16: [1, 4],
                32: [1, 5], 64: [1, 6], 128: [1, 7], 256: [1, 8],
                512: [1, 9], 1024: [1, 10]}
PROGRESS_OFFSET = [1, 16]


def unpack7(packed):
    """Roland transfer packing: 1 header byte carries the MSBs of 7 payload bytes."""
    out = bytearray()
    f = 0
    n = len(packed)
    while f < n:
        e = packed[f] << 7
        f += 1
        for _ in range(7):
            if f >= n:
                break
            out.append(packed[f] | (0x80 & e))
            f += 1
            e >>= 1
    return bytes(out)


def pack7(data):
    """Inverse of unpack7."""
    out = bytearray()
    for i in range(0, len(data), 7):
        group = data[i:i + 7]
        hdr = 0
        for j, b in enumerate(group):
            if b & 0x80:
                hdr |= 1 << j
        out.append(hdr)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def data_addresses():
    """Set of decoded addresses the device uses for bulk data chunks."""
    addrs = {}
    for size, off in DATA_OFFSETS.items():
        a = offset_address(UTILITY_ADDR, decode7(off))
        addrs[decode7(a)] = size
    return addrs


def read_blob(port, kind, ident, timeout=25.0, verbose=True):
    """Request a data blob (read-only) and reassemble it."""
    want = BLOB_SIZE[kind]
    addr = offset_address(UTILITY_ADDR, GET_OFFSETS[kind])
    prog = decode7(offset_address(UTILITY_ADDR, decode7(PROGRESS_OFFSET)))
    chunks = data_addresses()
    req_addr = decode7(addr)

    # Args are [index, count], each encoded as a 4-byte 7-bit value
    # (Tr8sDeviceController: `const c = 'system' === a ? null : [d, 1]`).
    args = encode7(ident, 4) + encode7(1, 4)
    port.drain()
    port.send(make_sysex(DT1, addr, args))
    if verbose:
        print(f"requested {kind} #{ident} "
              f"(addr {' '.join(f'{b:02X}' for b in addr)}), expecting {want} bytes")

    out = bytearray()
    buf = bytearray()
    t0 = time.time()
    while len(out) < want and time.time() - t0 < timeout:
        try:
            chunk = os.read(port.fd, 8192)
        except BlockingIOError:
            time.sleep(0.002)
            continue
        if not chunk:
            continue
        buf += bytes(b for b in chunk if b < 0xF8)
        msgs = parse_sysex(buf)
        if msgs:
            last_end = buf.rfind(0xF7)
            buf = buf[last_end + 1:] if last_end >= 0 else buf
        for m in msgs:
            if len(m) < 14 or m[7] != DT1:
                continue
            a = decode7(m[8:12])
            body = m[12:-2]
            if a in chunks:
                out += unpack7(body)
                t0 = time.time()
            elif a == prog and verbose:
                print(f"  progress: {body[0] if body else '?'}%")
            elif a == req_addr and body and body[0] != 0:
                print(f"  device refused request (status {body[0]})")
                return None
    return bytes(out[:want]) if out else None


def cmd_readpattern(pid, outdir="/home/svh/tr8s/notes"):
    path = None
    for p in PORTS:
        if os.path.exists(p):
            path = p
            break
    if not path:
        sys.exit("no rawmidi device")
    port = Port(path)
    blob = read_blob(port, "pattern", pid)
    port.close()
    if not blob:
        print("no data returned")
        return None
    os.makedirs(outdir, exist_ok=True)
    dest = os.path.join(outdir, f"pattern_{pid:03d}.bin")
    with open(dest, "wb") as f:
        f.write(blob)
    print(f"got {len(blob)} bytes -> {dest}")
    print(f"  first 32: {blob[:32].hex(' ')}")
    nz = sum(1 for b in blob if b)
    print(f"  non-zero bytes: {nz}/{len(blob)}")
    return blob


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("commands: probe | raw '<addr hex>' ['<data hex>'] [devId]")
        return
    if sys.argv[1] == "probe":
        cmd_probe()
    elif sys.argv[1] == "readpattern":
        cmd_readpattern(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif sys.argv[1] == "raw":
        cmd_raw(sys.argv[2],
                sys.argv[3] if len(sys.argv) > 3 else "00",
                int(sys.argv[4], 0) if len(sys.argv) > 4 else DEV_DEFAULT)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
