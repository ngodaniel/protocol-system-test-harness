import pytest
from qaharness.transport import msgtypes as mt
from qaharness.transport.framing import FrameError

def _corrupt_is_detected(sim_api, data_client):
    sim_api.configure()
    sim_api.set_faults(corrupt_rate=1.0, drop_rate=0.0, delay_ms=0)

    with pytest.raises(FrameError):
        data_client.request(mt.REQ_STATUS)

def test_corrupt_is_detected(sim_api, data_client):
    _corrupt_is_detected(sim_api, data_client)

    