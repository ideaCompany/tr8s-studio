"""
Layer 1 — transport. SysEx framing and bulk transfer. Knows nothing about
patterns, kits or music; it moves opaque blobs.

See docs/PROTOCOL.md for the wire format and how it was derived.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from . import config

ROLAND = 0x41
MODEL_TR8S = (0x00, 0x00, 0x00, 0x45)
DT1 = 0x12
RQ1 = 0x11
DEFAULT_DEVICE_ID = 0x10

UTILITY = (0x50, 0x00, 0x00, 0x00)

# The "temp" address space -- live state rather than stored data. Roland's own
# web client writes these three to move the machine to a pattern; they are
# write-only (an RQ1 to them gets no reply). Taken from the address table in
# `js/Tr8s/Tr8sData.js` and verified by listening to what the machine plays.
TEMP_CURRENT_KIT = (0x01, 0x00, 0x00, 0x00)
TEMP_CURRENT_PATTERN = (0x01, 0x00, 0x00, 0x01)
TEMP_NEXT_PATTERN = (0x01, 0x00, 0x00, 0x02)
TEMP_PATTERN_SELECT = (0x01, 0x00, 0x00, 0x1B)

CMD_OFFSETS = {
    "playing": 0x10, "lock": 0x11, "display": 0x12,
    "version": 0x13, "uid": 0x14, "optimize": 0x20,
    "free_area": 0x21, "free_tone_count": 0x22,
    "free_tone": 0x23, "delete_tone": 0x24,
}
GET_OFFSETS = {"system": 0x31, "pattern": 0x41, "kit": 0x51,
               "tone": 0x61, "pcm_tone": 0x71, "sample": 0x73}
SEND_OFFSETS = {"system": 0x30, "pattern": 0x40, "kit": 0x50,
                "tone": 0x60, "pcm_tone": 0x70, "sample": 0x72}
WRITE_OFFSETS = {"system": 0x00, "pattern": 0x01, "kit": 0x02, "tone": 0x03}
BLOB_SIZES = {"system": 752, "pattern": 24504, "kit": 1312,
              "tone": 36, "pcm_tone": 64}
# chunk size -> two-byte offset from the utility base
DATA_OFFSETS = {1 << i: [1, i] for i in range(11)}
PROGRESS_OFFSET = [1, 16]

MAX_SLOT = 127


class TransportError(RuntimeError):
    pass


def decode7(addr) -> int:
    v = 0
    for b in addr:
        v = (v << 7) | (b & 0x7F)
    return v


def encode7(value: int, n: int) -> list[int]:
    out = [0] * n
    for i in range(n - 1, -1, -1):
        out[i] = value & 0x7F
        value >>= 7
    return out


def offset_address(addr, offset: int, mult: int = 1) -> list[int]:
    return encode7(decode7(addr) + offset * mult, len(addr))


def checksum(payload) -> int:
    return 127 & (128 - (127 & sum(payload)))


def make_sysex(cmd: int, addr, data, device_id: int = DEFAULT_DEVICE_ID) -> bytes:
    payload = list(addr) + list(data)
    return bytes([0xF0, ROLAND, device_id, *MODEL_TR8S, cmd,
                  *payload, checksum(payload), 0xF7])


def split_sysex(buf: bytes) -> list[bytes]:
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


def pack7(data: bytes) -> bytes:
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


def unpack7(packed: bytes) -> bytes:
    out = bytearray()
    f, n = 0, len(packed)
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


@dataclass
class Transport:
    """
    A duplex rawmidi connection.

    The TR-8S streams MIDI clock and active sensing continuously, so every read
    discards bytes >= 0xF8 BEFORE judging whether data is still arriving --
    otherwise an idle timeout never expires and reads block forever.
    """

    path: str | None = None
    device_id: int = DEFAULT_DEVICE_ID
    fd: int | None = None
    on_realtime: object = None      # callable(bytes) for clock/start/stop
    on_channel: object = None       # callable(bytes) for channel voice messages
    _in_sysex: bool = False
    _buf: bytearray = field(default_factory=bytearray, repr=False)
    _lock: object = field(default_factory=threading.Lock, repr=False)
    _stop: object = field(default_factory=threading.Event, repr=False)
    _thread: object = None
    # Serialises whole request/response cycles. A SysEx exchange is stateful:
    # send, then read until the reply is complete. Two threads interleaving
    # (say a background pattern index and a user's step edit) would each
    # consume parts of the other's reply and both would see corruption.
    _io: object = field(default_factory=threading.RLock, repr=False)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def open(self):
        if self.fd is not None:
            return
        self.path = self.path or config.find_port()
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except FileNotFoundError as e:
            raise TransportError(f"{self.path} not found; is the TR-8S on?") from e
        except PermissionError as e:
            raise TransportError(
                f"no permission on {self.path}; add your user to the 'audio' group"
            ) from e
        os.set_blocking(self.fd, False)
        # One reader thread owns the fd, and everything in this process shares
        # it. The OS will happily let a second process open the same node, but
        # incoming bytes go to whichever reader asks first -- two readers split
        # the stream and both see corruption. Run one process at a time.
        self._stop.clear()
        self._buf.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True,
                                        name="tr8s-reader")
        self._thread.start()

    def _reader(self):
        while not self._stop.is_set():
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                time.sleep(0.0005)
                continue
            except OSError:
                break
            if not chunk:
                continue
            # Deliver realtime and channel bytes IN ARRIVAL ORDER. An earlier
            # version sorted each chunk into a clock pile and a note pile and
            # handed over the clocks first: every note in a 4 KB read was then
            # stamped with the step after the chunk's LAST clock, not the clock
            # it arrived beside. At 174 BPM a chunk spans several steps, so the
            # live picture smeared by up to a beat. Order is the whole point.
            sysex = bytearray()
            events = []              # (is_realtime, bytes) in order, coalesced
            for b in chunk:
                if b >= 0xF8:
                    if events and events[-1][0]:
                        events[-1][1].append(b)
                    else:
                        events.append((True, bytearray([b])))
                    continue
                if b == 0xF0:
                    self._in_sysex = True
                if self._in_sysex:
                    sysex.append(b)
                    if b == 0xF7:
                        self._in_sysex = False
                else:
                    if events and not events[-1][0]:
                        events[-1][1].append(b)
                    else:
                        events.append((False, bytearray([b])))
            if sysex:
                with self._lock:
                    self._buf += sysex
            for is_rt, payload in events:
                cb = self.on_realtime if is_rt else self.on_channel
                if payload and cb:
                    try:
                        cb(bytes(payload))
                    except Exception:
                        pass      # a broken listener must not kill the reader

    def close(self):
        self._stop.set()
        th = self._thread
        if th is not None:
            th.join(timeout=1.0)
            self._thread = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    # ---------------------------------------------------------------- io

    def drain(self):
        with self._lock:
            self._buf.clear()
        self._in_sysex = False

    def _take(self) -> bytes:
        with self._lock:
            out = bytes(self._buf)
            self._buf.clear()
        return out

    def send(self, msg: bytes):
        os.write(self.fd, msg)

    def collect(self, idle: float = 1.2, hard_cap: float = 20.0) -> bytes:
        """Gather buffered non-realtime bytes until `idle` seconds pass quietly."""
        buf = bytearray()
        last = start = time.time()
        while time.time() - last < idle and time.time() - start < hard_cap:
            got = self._take()
            if got:
                buf += got
                last = time.time()
            else:
                time.sleep(0.002)
        return bytes(buf)

    # ------------------------------------------------------------ commands

    def utility(self, name: str, data=(0,), idle: float = 1.2) -> list[bytes]:
        with self._io:
            addr = offset_address(UTILITY, CMD_OFFSETS[name])
            self.drain()
            self.send(make_sysex(DT1, addr, list(data), self.device_id))
            return split_sysex(self.collect(idle))

    def select_pattern(self, index: int, settle: float = 0.06):
        """
        Move the machine to a pattern, the way its own web client does.

        Three writes: the current pattern, the next pattern, and a bitmask of
        which of the sixteen pads in the bank is lit. Sending only the first
        does not move it.

        This is not a Program Change -- it works whether or not `Rx Prog Chg`
        is on, which on this machine it is not.
        """
        if not 0 <= int(index) <= 127:
            raise ValueError(f"pattern index {index} out of range 0..127")
        index = int(index)
        with self._io:
            for addr in (TEMP_CURRENT_PATTERN, TEMP_NEXT_PATTERN):
                self.send(make_sysex(DT1, list(addr), [index], self.device_id))
                time.sleep(settle)
            bits = 1 << (index % 16)
            nibbles = [(bits >> (4 * i)) & 0x0F for i in range(4)][::-1]
            self.send(make_sysex(DT1, list(TEMP_PATTERN_SELECT), nibbles,
                                 self.device_id))
            time.sleep(settle)

    def select_kit(self, index: int, settle: float = 0.06):
        """Move the machine to a kit. Same mechanism as select_pattern."""
        if not 0 <= int(index) <= 127:
            raise ValueError(f"kit index {index} out of range 0..127")
        with self._io:
            self.send(make_sysex(DT1, list(TEMP_CURRENT_KIT), [int(index)],
                                 self.device_id))
            time.sleep(settle)

    # ------------------------------------------------------------ samples

    def free_area(self) -> dict:
        """Sample memory: (total_free, longest_free, top_free_address) bytes.
        The reply is three 7-bit-packed uint32s."""
        for m in self.utility("free_area"):
            body = m[12:-2]
            if len(body) >= 12:
                v = [decode7(body[i:i + 4]) for i in (0, 4, 8)]
                return {"total_free": v[0], "longest_free": v[1],
                        "top_free_address": v[2]}
        raise TransportError("no reply to a free-area request")

    def free_tone(self) -> int:
        """The next free user tone id (>= 624), as a 7-bit-packed uint16."""
        for m in self.utility("free_tone"):
            body = m[12:-2]
            if len(body) >= 2:
                return decode7(body[:2])
        raise TransportError("no reply to a free-tone request")

    def send_sample(self, address: int, pcm: bytes, settle: float = 0.004) -> bool:
        """
        Put raw sample bytes into sample memory at `address`.

        The format the machine uses, read off one of its own user samples:
        16-bit signed little-endian PCM, mono, 44.1 kHz. Two 4-byte args --
        address and byte count -- then the data in 7-bit-packed chunks, the
        same framing as every other blob.
        """
        addr = offset_address(UTILITY, SEND_OFFSETS["sample"])
        with self._io:
            self.drain()
            self.send(make_sysex(DT1, addr,
                                 encode7(address, 4) + encode7(len(pcm), 4),
                                 self.device_id))
            time.sleep(0.05)
            return self._send_chunks(pcm, settle=settle)

    def delete_tone(self, tone_id: int) -> bool:
        """
        Remove a user tone and free its sample memory.

        Three steps, exactly as Roland's client does it -- the middle one alone
        replies with an error and leaves the tone in place:
          1. write temp.tone.category = 1 for the tone (marks it deletable)
          2. utility deleteTone with the id; a 0 reply means success
          3. commit the tone
        """
        if not 624 <= int(tone_id) <= 1023:
            raise ValueError(f"tone {tone_id} is not a user tone (624..1023)")
        tone_id = int(tone_id)
        with self._io:
            # temp.tone.category: base 30 00 00 10, per-tone block 01 00 00
            cat = offset_address((0x30, 0, 0, 0x10), tone_id, decode7((1, 0, 0)))
            self.send(make_sysex(DT1, cat, [1], self.device_id))
            time.sleep(0.08)
            ok = False
            for m in self.utility("delete_tone", data=encode7(tone_id, 2)):
                body = m[12:-2]
                if body:
                    ok = body[0] == 0
            if not ok:
                return False
            self.commit("tone", tone_id)
            return True

    def firmware(self) -> dict:
        msgs = self.utility("version")
        garbled = None
        for m in msgs:
            body = m[12:-2]
            txt = "".join(chr(c) for c in body if 32 <= c < 127)
            if txt.strip():
                if any(ch.isdigit() for ch in txt[:4]):
                    return {"version": txt[:4], "revision": txt[4:8]}
                garbled = txt[:8]
        raise TransportError(
            f"garbled reply to a version request ({garbled!r})"
            if garbled else
            "no reply to a version request; check the connection")

    def firmware_retry(self, attempts: int = 3) -> dict:
        """
        The first request after opening sometimes reads a garbled reply: the
        machine can still be mid-message from before we attached, and the
        reader stitches its tail onto our answer ("PPPP"). That is transient.
        A second process on the same port is NOT transient -- it garbles
        every reply -- so the distinction is made by trying again.
        """
        last = None
        for i in range(attempts):
            try:
                return self.firmware()
            except TransportError as e:
                last = e
                if "garbled" not in str(e):
                    break
                self.drain()
                time.sleep(0.3 * (i + 1))
        if last and "garbled" in str(last):
            raise TransportError(
                f"{last}: still garbled after {attempts} tries, so another "
                f"program is probably reading the same MIDI port. Run one at "
                f"a time.")
        raise last

    # --------------------------------------------------------------- blobs

    def read_blob(self, kind: str, index: int, timeout: float = 25.0) -> bytes | None:
        with self._io:
            """Read one blob. Read-only; safe at any time."""
            want = BLOB_SIZES[kind]
            addr = offset_address(UTILITY, GET_OFFSETS[kind])
            req = decode7(addr)
            prog = decode7(offset_address(UTILITY, decode7(PROGRESS_OFFSET)))
            chunk_addrs = {decode7(offset_address(UTILITY, decode7(off))): size
                           for size, off in DATA_OFFSETS.items()}

            self.drain()
            # two 4-byte args: index AND count. Index alone gets silence.
            self.send(make_sysex(DT1, addr, encode7(index, 4) + encode7(1, 4),
                                 self.device_id))

            out, buf = bytearray(), bytearray()
            last = time.time()
            while len(out) < want and time.time() - last < timeout:
                chunk = self._take()
                if not chunk:
                    time.sleep(0.002)
                    continue
                buf += chunk
                msgs = split_sysex(bytes(buf))
                if msgs:
                    end = buf.rfind(0xF7)
                    buf = buf[end + 1:] if end >= 0 else buf
                for m in msgs:
                    if len(m) < 14 or m[7] != DT1:
                        continue
                    a = decode7(m[8:12])
                    body = m[12:-2]
                    if a in chunk_addrs:
                        out += unpack7(body)
                        last = time.time()
                    elif a == req and body and body[0] != 0:
                        return None            # device refused
            return bytes(out[:want]) if len(out) >= want else None

    def send_blob(self, kind: str, slot: int, blob: bytes,
                  settle: float = 0.004, ack_wait: float = 0.20) -> bool:
        """
        Stream a blob into a slot.

        Transfer semantics, measured (see docs/PROTOCOL.md):
          * A transfer writes the SLOT immediately -- patterns and kits alike. It is
            visible on read-back and survives writing other slots, so it is NOT a
            scratch buffer.
          * Patterns are re-read by the sequencer at once, so an uncommitted pattern
            write is audible on the next loop. Kits are not: the loaded kit keeps
            playing until commit (or the user reselects it).
          * What commit() adds is presumed durability across power-off. UNTESTED --
            it needs a power cycle to confirm.
        """
        expect = BLOB_SIZES[kind]
        if len(blob) != expect:
            raise ValueError(f"{kind} blob is {len(blob)} bytes, expected {expect}")
        # patterns and kits have 128 slots; tones have 1024, of which
        # 624..1023 are the user's samples
        top = 1023 if kind in ("tone", "pcm_tone") else MAX_SLOT
        if not 0 <= slot <= top:
            raise ValueError(f"{kind} slot {slot} out of range 0..{top}")

        with self._io:
            init = offset_address(UTILITY, SEND_OFFSETS[kind])
            self.drain()
            self.send(make_sysex(DT1, init, encode7(slot, 4) + encode7(1, 4),
                                 self.device_id))
            time.sleep(0.05)
            self.collect(ack_wait, hard_cap=2.0)

            return self._send_chunks(blob, settle=settle)

    def _send_chunks(self, data: bytes, settle: float = 0.004) -> bool:
        """Stream `data` in the largest power-of-two chunks that fit; the
        chunk size selects the data address. Shared by blobs and samples."""
        pos = 0
        while pos < len(data):
            size = 1024
            while size and pos + size > len(data):
                size >>= 1
            if not size:
                break
            addr = offset_address(UTILITY, decode7(DATA_OFFSETS[size]))
            self.send(make_sysex(DT1, addr, pack7(data[pos:pos + size]),
                                 self.device_id))
            pos += size
            time.sleep(settle)
            self.drain()      # discard chunk acks without waiting on them
        return pos == len(data)

    def commit(self, kind: str, slot: int):
        with self._io:
            """
            The panel's WRITE. Send it after a transfer you want to keep.

            Note that a transfer alone already changes the slot as read back; the
            measured difference is that kits do not become audible until this is
            sent. Durability across power-off is the presumed purpose but has not
            been verified here.
            """
            addr = offset_address(UTILITY, WRITE_OFFSETS[kind])
            self.send(make_sysex(DT1, addr, encode7(slot, 2), self.device_id))
            time.sleep(0.5)
            self.collect(0.6, hard_cap=3.0)

    def note(self, note: int, velocity: int = 110, channel: int = 9,
             length: float = 0.05):
        with self._io:
            self.send(bytes([0x90 | channel, note, velocity]))
            time.sleep(length)
            self.send(bytes([0x80 | channel, note, 0]))
