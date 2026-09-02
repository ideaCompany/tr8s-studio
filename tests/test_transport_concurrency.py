"""
The transport is shared: a background pattern index, the live monitor and a
user's edit all run against one port. A SysEx exchange is stateful (send, then
read until the reply completes), so two threads interleaving would each consume
part of the other's reply. These tests pin that serialisation down.
"""

import threading
import time

import pytest

from tr8s.transport import Transport


class Tracker:
    """A lock that records whether two holders ever overlapped."""

    def __init__(self):
        self._real = threading.RLock()
        self.depth = 0
        self.max_depth = 0
        self.overlapped = False
        self._guard = threading.Lock()

    def __enter__(self):
        self._real.acquire()
        with self._guard:
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            if self.depth > 1:
                self.overlapped = True
        return self

    def __exit__(self, *exc):
        with self._guard:
            self.depth -= 1
        self._real.release()


def _transport_with_tracker():
    t = Transport(path="fake")
    t._io = Tracker()
    return t


def test_commit_is_serialised():
    t = _transport_with_tracker()
    sent = []
    t.send = lambda msg: (time.sleep(0.02), sent.append(msg))
    t.collect = lambda *a, **k: b""

    threads = [threading.Thread(target=t.commit, args=("pattern", i))
               for i in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert len(sent) == 6
    assert not t._io.overlapped, "two commits held the port at once"
    assert t._io.max_depth == 1


def test_send_blob_is_serialised():
    t = _transport_with_tracker()
    order = []
    def fake_send(msg):
        order.append("s")
        time.sleep(0.001)
    t.send = fake_send
    t.collect = lambda *a, **k: b""
    t.drain = lambda: None

    blob = bytes(1312)
    threads = [threading.Thread(target=t.send_blob, args=("kit", i, blob))
               for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not t._io.overlapped, "two transfers interleaved on the wire"


def test_read_blob_is_serialised():
    t = _transport_with_tracker()
    t.send = lambda msg: None
    t.drain = lambda: None
    # never returns data: the point is only that the lock is held exclusively
    t._take = lambda: b""

    threads = [threading.Thread(target=t.read_blob, args=("tone", i, 0.05))
               for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not t._io.overlapped


def test_lock_is_reentrant():
    """A guarded method may call another; a plain Lock would deadlock."""
    t = Transport(path="fake")
    with t._io:
        with t._io:
            pass          # reaching here at all is the assertion


def test_validation_happens_before_the_lock_is_taken():
    """A bad argument must fail fast, not queue behind other traffic."""
    t = _transport_with_tracker()
    with pytest.raises(ValueError):
        t.send_blob("kit", 0, b"too short")
    with pytest.raises(ValueError):
        t.send_blob("kit", 999, bytes(1312))
    assert t._io.max_depth == 0, "the lock should never have been acquired"


def test_the_reader_delivers_clock_and_notes_in_arrival_order():
    """
    The reader used to sort each chunk into a clock pile and a note pile and
    deliver the clocks first, so every note in a chunk was stamped with the
    step after the chunk's LAST clock. Order across the two callbacks is the
    whole point, so check the interleaving, not just that both arrive.
    """
    import os
    from tr8s.transport import Transport

    r, w = os.pipe()
    t = Transport.__new__(Transport)
    t.fd = r
    t.on_realtime = None
    t.on_channel = None
    t._in_sysex = False
    t._buf = bytearray()
    import threading
    t._lock = threading.Lock()
    t._stop = threading.Event()

    order = []
    t.on_realtime = lambda d: order.extend(("clk",) * len(d))
    t.on_channel = lambda d: order.append(("note", bytes(d)))

    # clock, note, clock, clock, note -- in one chunk. Stop the reader after
    # that chunk: on a real device an empty read never happens, but on a
    # closed pipe it is EOF and the loop would spin forever.
    os.write(w, bytes([0xF8, 0x99, 36, 100, 0xF8, 0xF8, 0x99, 38, 100]))
    os.close(w)
    os.set_blocking(r, False)
    real_read = os.read

    def one_chunk(fd, n):
        data = real_read(fd, n)
        t._stop.set()
        return data
    os.read = one_chunk
    try:
        t._reader()
    finally:
        os.read = real_read
        os.close(r)

    kinds = [x if x == "clk" else "note" for x in order]
    assert kinds == ["clk", "note", "clk", "clk", "note"], kinds
