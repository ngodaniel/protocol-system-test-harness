from __future__ import annotations
import socket
from dataclasses import dataclass
from qaharness.utils.retry import RetryPolicy, with_retries
from qaharness.transport.framing import encode_frame, decode_frame, FrameError
from qaharness.transport import msgtypes as mt

@dataclass(frozen=True)
class UdpEndpoint:
    host: str
    port: int

class UdpClient:
    def __init__(self, endpoint: UdpEndpoint, timeout_s: float = 1.0):
        self._endpoint = endpoint
        self._timeout_s = timeout_s

    def request_once(self, msg_type: int, payload: bytes = b"", recv_buf: int = 4096) -> bytes:
        pkt = encode_frame(msg_type, payload)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout_s)
        try:
            sock.sendto(pkt, (self._endpoint.host, self._endpoint.port))
            data, _ = sock.recvfrom(recv_buf)
        finally:
            sock.close()

        # CRC + frame validation
        frame = decode_frame(data)
        return frame.msg_type, frame.payload # tuple

    def request(self, msg_type, payload: bytes = b"", *, policy: RetryPolicy | None = None) -> bytes:
        if policy is None:
            return self.request_once(msg_type, payload)
        return with_retries(lambda: self.request_once(msg_type, payload), policy)
    
    # convenience helpers used by tests
    def ping(self):
        rtype, payload = self.request(mt.REQ_PING)
        return rtype, payload
    
    def status(self):
        rtype, payload = self.request(mt.REQ_STATUS)
        return rtype, payload
    
    def start(self):
        rtype, payload = self.request(mt.REQ_START)
        return rtype, payload
    
    def stop(self):
        rtype, payload = self.request(mt.REQ_STOP)
        return rtype, payload
    
    @staticmethod
    def assert_not_corrupt(response: bytes) -> None:
        """
        for this dmeo: treat responses ending with X/Y as corrupted.
        replace later with CRC/checksum validation in framing.py
        """
        if response.endswith(b"X") or response.endswith(b"Y"):
            raise ValueError(f"Corrupt response detected: {response!r}")