import pytest
from qaharness.utils.retry import RetryPolicy

def test_corrupt_is_detected(sim_api, sim_udp):
    sim_api.configure()
    sim_api.set_faults(corrupt_rate=1.0, drop_rate=0.0, delay_ms=0)

    # we expect corruption; use retries to show it is consistently corrupt
    resp = sim_udp.request(b"STATUS")#, policy=RetryPolicy(attempts=3))
    with pytest.raises(ValueError):
        sim_udp.assert_not_corrupt(resp)

    