import os
import socket

from qaharness.transport import msgtypes as mt
UDP_HOST = os.getenv("SIM_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("SIM_UDP_PORT", "9000"))


def test_udp_ping_pong(sim_udp):
    rtype, payload = sim_udp.ping()
    assert rtype == mt.RESP_OK
    assert payload == b"PONG"

    
