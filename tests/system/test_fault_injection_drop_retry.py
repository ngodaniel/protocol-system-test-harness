import pytest
from qaharness.utils.retry import RetryPolicy
from qaharness.transport import msgtypes as mt

@pytest.mark.system
def test_udp_drop_rate_with_retries(sim_api, sim_udp):
    # configure to keep state-related errors out of the way
    sim_api.configure()

    # drop most packes; retries should eventually succeed sometimes
    sim_api.set_faults(drop_rate=0.7, delay_ms=0, corrupt_rate=0.0)

    policy = RetryPolicy(
        attempts=10, 
        initial_backoff_s=0.01,
        max_backoff_s=0.05,
        multiplier=2.0,
        jitter_ratio=0.1,
        retry_exceptions=(TimeoutError,),
        timeout_s=2.0,
        #base_delay_s=0.01, max_delay_s=0.05
    )
    rtype, payload = sim_udp.request(mt.REQ_STATUS, policy=policy)
    assert rtype == mt.RESP_STATE
    assert payload in (b"CONFIGURED", b"STREAMING", b"IDLE")




