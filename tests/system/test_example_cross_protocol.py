import time
import pytest

from qaharness.transport import msgtypes as mt
from qaharness.transport.framing import FrameError

@pytest.mark.system
def test_cross_protocol_state_and_faults(sim_api, sim_udp):
    """
    example system level test
    - verify initial state over udp
    - attemp illegal UDP transition (START with IDLE)
    - configure via HTTP, then start via UDP (cross-protocol)
    - inject corrupt and insert CRC/frame validation trips
    """
    #1) sanity: simulator is alive over HTTP, starts IDLE (reset fixture guarantees clean start)
    http_status = sim_api.status()
    assert http_status["state"] == "IDLE"

    #2) UDP status returns the same state (RESP_STATE + payload)
    rtype, payload = sim_udp.status()
    assert rtype == mt.RESP_STATE
    assert payload == b"IDLE"

    #3) illegal UDP start while IDLE -> RESP_ERROR + BAD_STATE
    rtype, payload = sim_udp.start()
    assert rtype == mt.RESP_ERR
    assert payload == b"BAD_STATE"

    #4) cross-protocol transition: configure via HTTP
    sim_api.configure()
    rtype, payload = sim_udp.status()
    assert rtype == mt.RESP_STATE
    assert payload == b"CONFIGURED"

    # then start streaming via UDP (state mutates after response decision in simulator)
    rtype, payload = sim_udp.start()
    assert rtype == mt.RESP_OK
    assert payload == b"STREAMING"

    #5) fault injection example: packet loss
    # we'll use a tiny manual retry loop (keeps the example independent of RetryPolicy internals)
    sim_api.set_faults(drop_rate=0.7, delay_ms=0, corrupt_rate=0.0)
    got_pong = False
    for _ in range(15):
        try:
            rtype, payload = sim_udp.ping()
            if (rtype, payload) == (mt.RESP_OK, b"PONG"):
                got_pong = True
                break
        except TimeoutError:
            pass
        time.sleep(0.05)

    assert got_pong, "Expected at least one successful UDP ping despite packet loss"

    #6) fault injection example: corruption -> CRC mismatch -> FrameError from decode_frame()
    sim_api.set_faults(drop_rate=0.0, delay_ms=0, corrupt_rate=1.0)

    with pytest.raises(FrameError):
        sim_udp.ping()
