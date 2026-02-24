import struct

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from qaharness.transport.framing import (
    FrameError,
    encode_frame,
    decode_frame,
)

"""
Why these tests matter
- round-trip property proves encoder/decoder symmetry across hundred of random inputs
- arbitrary-bytes fuzzing proves decode is resillient
- bit-flip CRC tests prove integrity checks actually catch corruption
"""
# constants copied from framing contract (header: 2s, B, B, H and CRC32)
_HDR_FMT = "!2sBBH"
_HDR_SIZE = struct.calcsize(_HDR_FMT)
_CRC_FMT = "!I"
_CRC_SIZE = struct.calcsize(_CRC_FMT)

""" round-trip properties """

@given(
    msg_type=st.integers(min_value=0, max_value=255),
    payload=st.binary(min_size=0, max_size=2048),   # keep fast; still plenty of coverage
)

@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_encode_decode_roundtrip(msg_type: int, payload:bytes):
    packet = encode_frame(msg_type, payload)
    frame = decode_frame(packet)
    
    assert frame.msg_type == msg_type
    assert frame.payload == payload

""" encoder guards """

@given(msg_type=st.one_of(st.integers(max_value=-1), st.integers(min_value=256)))
def test_encode_rejects_out_of_range_msg_type(msg_type: int):
    with pytest.raises(ValueError):
        encode_frame(msg_type, b"")

def test_encode_rejects_too_large_payload():
    # framing.py caps payload at 65535 bytes
    with pytest.raises(ValueError):
        encode_frame(1, b"x" * 65536)

""" decoder robustness / fuzzing """

@given(packet=st.binary(min_size=0, max_size=4096))
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_decode_never_crashes_on_arbitrary_bytes(packet: bytes):
    """
    fuzz invariant:
        decode_frame should either return a valid frame or raise FrameError,
        but not crash with unreleated exceptions.
    """
    try:
        frame = decode_frame(packet)
        assert isinstance(frame.msg_type, int)
        assert isinstance(frame.payload, (bytes, bytearray))
    except FrameError:
        pass

@given(
    msg_type=st.integers(min_value=0, max_value=255),
    payload=st.binary(min_size=0, max_size=512),
    bit_index=st.integers(min_value=0, max_value=7),
)
@settings(max_examples=200)
def test_crc_detects_single_bit_flip_in_body(msg_type: int, payload: bytes, bit_index: int):
    """
    flipping a bit in header/payload (excluding CRC bytes) should cause CRC mismatch
    """
    packet = bytearray(encode_frame(msg_type, payload))

    # ensure there is at least one non-CRC byte to mutate
    body_len = len(packet) - _CRC_SIZE
    assert body_len > 0

    # flip one bit at a deterministic position within body
    pos = body_len // 2
    packet[pos] ^= (1 << bit_index)

    with pytest.raises(FrameError):
        decode_frame(bytes(packet))

@given(
    msg_type=st.integers(min_value=0, max_value=255),
    payload=st.binary(min_size=0, max_size=512),
)
def test_corrupting_crc_field_is_rejected(msg_type: int, payload: bytes):
    packet = bytearray(encode_frame(msg_type, payload))

    # flip one byte in CRC field
    packet[-1] ^= 0xFF

    with pytest.raises(FrameError):
        decode_frame(bytes(packet))


""" targeted malformed-frame tests (header semantics) """

@given(
    msg_type=st.integers(min_value=0, max_value=255),
    payload=st.binary(min_size=0, max_size=128),
)
def test_bad_magic_rejected(msg_type: int, payload: bytes):
    packet = bytearray(encode_frame(msg_type, payload))
    # header starts with MAGIC (2 bytes)
    packet[0] ^= 0x01   # break magic

    with pytest.raises(FrameError):
        decode_frame(bytes(packet))

@given(
    msg_type=st.integers(min_value=0, max_value=255),
    payload=st.binary(min_size=0, max_size=128),
)
def test_bad_version_rejected(msg_type: int, payload: bytes):
    packet = bytearray(encode_frame(msg_type, payload))
    # header layout: MAGIC(2), VER(1), TYPE(1), LEN(2)
    packet[2] = (packet[2] + 1) % 256   # mutate version byte

    with pytest.raises(FrameError):
        decode_frame(bytes(packet))




