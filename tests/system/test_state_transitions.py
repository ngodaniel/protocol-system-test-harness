import pytest

def test_udp_start_requires_configured(sim_api, sim_udp):
    # intially IDLE
    assert sim_api.status()["state"] == "IDLE"

    # START via UDP should fail in IDLE
    resp = sim_udp.request(b"START")
    assert resp == b"ERR:BAD_STATE"

    # configure via HTTP then START via UDP should succeed
    sim_api.configure()
    resp = sim_udp.request(b"START")
    assert resp == b"OK:STREAMING"

    #STOP should succeed now
    resp = sim_udp.request(b"STOP")
    assert resp == b"OK:STOPPED"