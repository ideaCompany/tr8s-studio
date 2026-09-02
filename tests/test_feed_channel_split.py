"""Channel messages split across payloads by an interleaved clock must survive.

Pattern-follow reads Program Change; while the machine plays, a clock byte can
land between the PC status byte and its value, ending one reader payload and
starting the next. Parsed per-payload the PC was dropped and follow died."""
from tr8s.monitor import Monitor


def test_a_program_change_split_across_two_payloads_is_reassembled():
    m = Monitor()
    # 0xC9 = Program Change on channel 9 (the pattern channel); value 117.
    m.feed_channel(bytes([0xC9]))          # clock split the message here
    assert m.state.pattern is None          # nothing complete yet
    m.feed_channel(bytes([117]))           # the value arrives next payload
    assert m.state.pattern == 117
    assert m.state.pattern_channel == 9
    assert 9 in m.state.program_channels


def test_a_whole_program_change_in_one_payload_still_works():
    m = Monitor()
    m.feed_channel(bytes([0xC9, 113]))
    assert m.state.pattern == 113 and 9 in m.state.program_channels


def test_a_note_split_across_payloads_is_reassembled():
    m = Monitor()
    m.feed_channel(bytes([0x99, 36]))      # note-on ch9, note 36 (BD), no vel yet
    assert not m.state.hits
    m.feed_channel(bytes([100]))           # velocity arrives next
    assert m.state.hits and m.state.hits[-1][2] == "BD"


def test_two_messages_back_to_back_both_parse():
    m = Monitor()
    m.feed_channel(bytes([0xC0, 85, 0xC9, 117]))   # kit PC then pattern PC
    assert m.state.pattern == 117
    assert 0 in m.state.program_channels and 9 in m.state.program_channels
