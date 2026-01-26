import os
import socket

UDP_HOST = os.getenv("SIM_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("SIM_UDP_PORT", "9000"))


def test_udp_ping_pong(sim_udp):
    assert sim_udp.request(b"PING") == b"PONG"
