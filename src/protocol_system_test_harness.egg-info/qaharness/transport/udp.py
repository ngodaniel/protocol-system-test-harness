from __future__ import annotations
import socket
from dataclasses import dataclass

@dataclass(frozen=True)
class UdpEndpoint:
    host: str
    port: int

class UdpClient:
    def __init__(self, endpoint: UdpEndpoint, timeout_s: float=1.5):
        self._endpoint = endpoint
        self._timeout_s = timeout_s

    def request(self, payload: bytes, recv_buf: int=4096) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.timeout(self._timeout_s)
        try:
            sock.sendto(payload, (self._endpoint.host, self._endpoint.port))
            data, _ = sock.recvfrom(recv_buf)
            return data
        finally:
            sock.close()


    
