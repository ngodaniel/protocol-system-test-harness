from __future__ import annotations
import socket
import struct
from dataclasses import dataclass
from qaharness.utils.retry import RetryPolicy, with_retries
from qaharness.transport.framing import encode_frame, decode_frame
from qaharness.transport import msgtypes as mt

_HDR_FMT = "!2sBBH"
_HDR_SIZE = struct.calcsize(_HDR_FMT)
_CRC_SIZE = 4

@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int

class TcpClient:
    def __init__(self, endpoint: TcpEndpoint, timeout_s: float = 1.0):
        self._endpoint = endpoint
        self._timeout_s = timeout_s

    def _recv_ext(self, sock: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise TimeoutError("socket closed before receving full response") 
            buf.extend(chunk)
        return bytes(buf)
    
    def request_once(self, msg_type: int, payload:bytes = b"") -> tuple[int, bytes]:
        pkt = encode_frame(msg_type, payload)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._timeout_s)
            sock.connect((self._endpoint.host, self._endpoint.port))
            sock.sendall(pkt)

            # read header first to learn payload length
            hdr = self._recv_ext(sock, _HDR_SIZE)
            magic, ver, rtype, length = struct.unpack(_HDR_FMT, hdr)

            rest = self._recv_ext(sock, length + _CRC_SIZE)
            full = hdr + rest

        frame = decode_frame(full)

        return frame.msg_type, frame.payload
    
    def request(self, msg_type: int, payload:bytes =b"", *, policy: RetryPolicy | None = None) -> tuple[int, bytes]:
        if policy is None:
            return self.request_once(msg_type, payload)
        return with_retries(lambda: self.request_once(msg_type, payload), policy)
    
    def ping(self): return self.request(mt.REQ_PING)
    def status(self): return self.request(mt.REQ_STATUS)
    def start(self): return self.request(mt.REQ_START)
    def stop(self): return self.request(mt.REQ_STOP)