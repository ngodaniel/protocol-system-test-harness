import pytest 
from qaharness.transport import msgtypes as mt

@pytest.mark.smoke
def test_tcp_ping(sim_tcp):
    rtype, payload = sim_tcp.ping()
    assert (rtype, payload) == (mt.RESP_OK, b"PONG")

    