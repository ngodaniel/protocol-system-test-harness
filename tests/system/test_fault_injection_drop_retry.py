from qaharness.utils.retry import RetryPolicy

def test_udp_drop_rate_with_retries(sim_api, sim_udp):
    # configure to keep state-related errors out of the way
    sim_api.configure()

    # drop most packes; retries should eventually succeed sometimes
    sim_api.set_faults(drop_rate=0.7, delay_ms=0, corrupt_rate=0.0)

    policy = RetryPolicy(attempts=10, base_delay_s=0.01, max_delay_s=0.05)
    resp=sim_udp.request(b"STATUS", policy=policy)
    assert resp.startswith(b"STATE=")


