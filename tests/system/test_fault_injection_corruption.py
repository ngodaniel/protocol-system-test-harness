import pytest
from qaharness.utils.retry import RetryPolicy
from qaharness.transport import msgtypes as mt
from qaharness.transport.framing import FrameError

def test_corrupt_is_detected(sim_api, sim_udp):
    sim_api.configure()
    sim_api.set_faults(corrupt_rate=1.0, drop_rate=0.0, delay_ms=0)

    with pytest.raises(FrameError):
        sim_udp.request(mt.REQ_STATUS)

    