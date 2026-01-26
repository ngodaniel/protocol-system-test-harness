from __future__ import annotations
import socket
from dataclasses import dataclass
from qaharness.utils.retry import RetryPolicy, with_retries

@dataclass(frozen=True)
class UdpEndpoint:
    host: str
    port: int

class UdpClient:
    def __init__(self, endpoint: UdpEndpoint, timeout_s: float = 1.5):
        self._endpoint = endpoint
        self._timeout_s = timeout_s

    def request_once(self, payload: bytes, recv_buf: int = 4096) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout_s)
        try:
            sock.sendto(payload, (self._endpoint.host, self._endpoint.port))
            data, _ = sock.recvfrom(recv_buf)
            return data
        finally:
            sock.close()

    def request(self, payload: bytes, recv_buf: int = 4096) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout_s)
        try:
            sock.sendto(payload, (self._endpoint.host, self._endpoint.port))
            data, _ = sock.recvfrom(recv_buf)
            return data
        finally:
            sock.close()

    def request(self, payload: bytes, *, policy: RetryPolicy | None = None) -> bytes:
        if policy is None:
            return self.request_once(payload)
        return with_retries(lambda: self.request_once(payload), policy)
    
    @staticmethod
    def assert_not_corrupt(response: bytes) -> None:
        """
        for this dmeo: treat responses ending with X/Y as corrupted.
        replace later with CRC/checksum validation in framing.py
        """
        if response.endswith(b"X") or response.endswith(b"Y"):
            raise ValueError(f"Corrupt response detected: {response!r}")