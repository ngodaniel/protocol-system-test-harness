from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

MAGIC = b"QA"
VERSION = 1


# header: MAGIC(2), VER(1), TYPE(1), LEN(2) => total 6 bytes
_HDR_FMT = "!2sBBH"
_HDR_SIZE = struct.calcsize(_HDR_FMT)
_CRC_FMT = "!I"
_CRC_SIZE = struct.calcsize(_CRC_FMT)

class FrameError(Exception):
    pass

@dataclass(frozen=True)
class Frame:
    msg_type: int
    payload: bytes

def encode_frame(msg_type: int, payload:bytes) -> bytes:
    if not (0 <= msg_type <= 255):
        raise ValueError("msg_type must fit in a byte")
    if len(payload) > 65535:
        raise ValueError("payload too large")
    
    header = struct.pack(_HDR_FMT, MAGIC, VERSION, msg_type, len(payload))
    body = header + payload
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(_CRC_FMT, crc)

def decode_frame(packet: bytes) -> Frame:
    if len(packet) < _HDR_SIZE + _CRC_SIZE:
        raise FrameError("packet too short")
    
    header = packet[:_HDR_SIZE]
    magic, ver, msg_type, length = struct.unpack(_HDR_FMT, header)

    if magic != MAGIC:
        raise FrameError("bag magic")
    if ver != VERSION:
        raise FrameError("unsupported version")
    
    payload = packet[_HDR_SIZE:_HDR_SIZE + length]
    crc_recv = struct.unpack(_CRC_FMT, packet[-_CRC_SIZE:])[0]

    crc_calc = zlib.crc32(packet[:-_CRC_SIZE]) & 0xFFFFFFFF
    if crc_calc != crc_recv:
        raise FrameError("crc mismatch")
    
    return Frame(msg_type=msg_type, payload=payload)