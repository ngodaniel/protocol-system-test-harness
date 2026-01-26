import pytest

from qaharness.transport import msgtypes as mt

def test_udp_start_requires_configured(sim_api, sim_udp):
    # intially IDLE
    assert sim_api.status()["state"] == "IDLE"

    # START via UDP should fail in IDLE
    rtype, payload = sim_udp.start()
    assert rtype == mt.RESP_ERR
    assert payload == b"BAD_STATE"

    # configure via HTTP then START via UDP should succeed
    sim_api.configure()
    rtype, payload = sim_udp.start()
    assert rtype == mt.RESP_OK
    assert payload == b"STREAMING"

    # STOP should succeed now
    rtype, payload = sim_udp.stop()
    assert rtype == mt.RESP_OK
    assert payload == b"STOPPED"
