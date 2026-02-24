import os
import pytest
import time
from qaharness.transport import msgtypes as mt
from qaharness.utils.retry import RetryPolicy, with_retries

"""
the repo explicitly models:
- fault injection (drop, delay, corruption) 
- retry policy correctness as a test target, not just functionality

this test suite upgrades that into measurable acceptance criteria
- reliability envelope (success rate under loss)
- latency envelope (p50/p95 under delay + retries)
"""
def percentile(values, p):
    if not values:
        raise ValueError("no values")
    vals = sorted(values)
    k = (len(vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return vals[f]
    return vals[f] + (vals[c] - vals[f]) * (k - f)

@pytest.mark.system
def test_delay_envelope_udp_ping(sim_api, sim_udp, metrics_recorder):
    """
    Envelope test: with a configured delay fault, PING response latency should
    track the injected delay within a reasonable tolerance
    """
    # clean baseline
    sim_api.reset()
    sim_api.set_faults(drop_rate=0.0, delay_ms=120, corrupt_rate=0.0)

    samples_ms = []
    n = 12

    for _ in range(n):
        t0 = time.perf_counter()
        rtype, payload = sim_udp.ping()
        dt_ms = (time.perf_counter() - t0) * 1000.0

        assert (rtype, payload) == (mt.RESP_OK, b"PONG")
        samples_ms.append(dt_ms)

    p50 = percentile(samples_ms, 50)
    p95 = percentile(samples_ms, 95)

    metrics_recorder({
        "name": "delay_envelope_udp_ping",
        "faults": {"drop_rate": 0.0, "delay_ms": 120, "corrupt_rate": 0.0},
        "samples": n,
        "latency_ms": {
            "min": min(samples_ms),
            "max": max(samples_ms),
            "mean": sum(samples_ms) / len(samples_ms),
            "p50": p50,
            "p95": p95,
        }
    })
    # evnvolope assertions (tune if CI is noisy)
    # lower bound ensures delay is actually applied
    assert p50 >= 100, f"p50 too low, dleay fault may not be applied: {p50:.1f}ms"
    # upper bound allows overhead/jitter but catches regressions
    assert p95 <= 400, f"p95 too high under 120ms delay: {p95:.1f}ms"

@pytest.mark.system
def test_drop_envelope_with_retries_udp_ping(sim_api, sim_udp_perf, metrics_recorder):
    """
    Drop-only degradation envelope:
      - injects packet loss (no delay/corruption)
      - validates retry-assisted success rate
      - records latency + retry behavior
      - uses env-tunable thresholds for CI stability
    """
    # --- Tunables ---
    attempts = int(os.getenv("PERF_DROP_SAMPLES", "50"))
    drop_rate = float(os.getenv("PERF_DROP_RATE", "0.35"))

    min_success_rate = float(os.getenv("PERF_DROP_MIN_SUCCESS_RATE", "0.85"))
    p95_max_ms = float(os.getenv("PERF_DROP_P95_MAX_MS", "750"))

    retry_attempts = int(os.getenv("PERF_DROP_RETRY_ATTEMPTS", "4"))
    retry_initial_backoff_s = float(os.getenv("PERF_DROP_RETRY_INITIAL_BACKOFF_S", "0.02"))
    retry_max_backoff_s = float(os.getenv("PERF_DROP_RETRY_MAX_BACKOFF_S", "0.10"))
    retry_multiplier = float(os.getenv("PERF_DROP_RETRY_MULTIPLIER", "2.0"))
    retry_jitter_ratio = float(os.getenv("PERF_DROP_RETRY_JITTER_RATIO", "0.10"))

    sim_api.reset()
    sim_api.set_faults(drop_rate=drop_rate, delay_ms=0, corrupt_rate=0.0)

    policy = RetryPolicy(
        attempts=retry_attempts,
        initial_backoff_s=retry_initial_backoff_s,
        max_backoff_s=retry_max_backoff_s,
        multiplier=retry_multiplier,
        jitter_ratio=retry_jitter_ratio,
        retry_exceptions=(TimeoutError,),
    )

    successes = 0
    timeouts = 0
    latencies_ms = []
    retry_event_counts = []
    total_retry_events = 0
    retry_events = []
    for _ in range(attempts):
        retry_events_for_request = 0

        def _on_retry(attempt_num, exc, sleep_s):
            nonlocal retry_events_for_request, total_retry_events
            retry_events_for_request += 1
            total_retry_events += 1
            retry_events.append({
                "request_name": "REQ_PING",     # or "REQ_STATUS"
                "attempt": attempt_num,
                "sleep_s": sleep_s,
                "error": type(exc).__name__,
            })

        t0 = time.perf_counter()
        try:
            rtype, payload = with_retries(
                lambda: sim_udp_perf.request_once(mt.REQ_PING),
                policy,
                on_retry=_on_retry,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0

            if (rtype, payload) == (mt.RESP_OK, b"PONG"):
                successes += 1
                latencies_ms.append(dt_ms)

            retry_event_counts.append(retry_events_for_request)

        except TimeoutError:
            timeouts += 1
            retry_event_counts.append(retry_events_for_request)
        
    success_rate = successes / attempts

    # Latency stats (successful requests only)
    p50 = percentile(latencies_ms, 50) if latencies_ms else None
    p95 = percentile(latencies_ms, 95) if latencies_ms else None
    mean_ms = (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None

    # Retry stats (all requests)
    retries_per_request_p95 = percentile(retry_event_counts, 95) if retry_event_counts else 0
    retries_per_request_mean = (
        sum(retry_event_counts) / len(retry_event_counts) if retry_event_counts else 0.0
    )

    metrics_recorder({
        "name": "drop_envelope_with_retries_udp_ping",
        "faults": {
            "drop_rate": drop_rate,
            "delay_ms": 0,
            "corrupt_rate": 0.0,
        },
        "samples": attempts,
        "results": {
            "successes": successes,
            "timeouts": timeouts,
            "success_rate": success_rate,
        },
        "latency_ms": {
            "count": len(latencies_ms),
            "mean": mean_ms,
            "p50": p50,
            "p95": p95,
            "min": min(latencies_ms) if latencies_ms else None,
            "max": max(latencies_ms) if latencies_ms else None,
        },
        "retry": {
            "policy": {
                "attempts": retry_attempts,
                "initial_backoff_s": retry_initial_backoff_s,
                "max_backoff_s": retry_max_backoff_s,
                "multiplier": retry_multiplier,
                "jitter_ratio": retry_jitter_ratio,
            },
            "total_retry_events": total_retry_events,
            "retries_per_request_mean": retries_per_request_mean,
            "retries_per_request_p95": retries_per_request_p95,
            "events": retry_events,
        },
        "thresholds": {
            "min_success_rate": min_success_rate,
            "p95_max_ms": p95_max_ms,
        },
    })

    # --- Assertions ---
    assert success_rate >= min_success_rate, (
        f"success_rate too low: {success_rate:.2%} "
        f"(samples={attempts}, drop={drop_rate}, retries={retry_attempts})"
    )

    # Latency envelope is only meaningful if we had successes
    assert latencies_ms, "No successful responses recorded; cannot evaluate latency envelope"

    assert p95 is not None and p95 <= p95_max_ms, (
        f"retry p95 too high: {p95:.1f}ms "
        f"(threshold {p95_max_ms}ms; consider tuning retries or drop rate)"
    )


@pytest.mark.system
def test_combined_drop_and_delay_envelope(sim_api, sim_udp_perf, metrics_recorder):
    """
    Combined degradation envelope:
      - applies both drop + delay faults
      - validates success-rate with retries
      - records latency + retry behavior
      - uses env-tunable sample size/thresholds for CI stability
    """

    # --- Tunables (safe defaults for CI) ---
    attempts = int(os.getenv("PERF_COMBINED_SAMPLES", "60"))
    drop_rate = float(os.getenv("PERF_COMBINED_DROP_RATE", "0.20"))
    delay_ms = int(os.getenv("PERF_COMBINED_DELAY_MS", "80"))

    min_success_rate = float(os.getenv("PERF_COMBINED_MIN_SUCCESS_RATE", "0.80"))
    p50_min_ms = float(os.getenv("PERF_COMBINED_P50_MIN_MS", "70"))
    p95_max_ms = float(os.getenv("PERF_COMBINED_P95_MAX_MS", "900"))

    # Retry tuning (these are usually what drives tail latency)
    retry_attempts = int(os.getenv("PERF_COMBINED_RETRY_ATTEMPTS", "4"))
    retry_initial_backoff_s = float(os.getenv("PERF_COMBINED_RETRY_INITIAL_BACKOFF_S", "0.02"))
    retry_max_backoff_s = float(os.getenv("PERF_COMBINED_RETRY_MAX_BACKOFF_S", "0.10"))
    retry_multiplier = float(os.getenv("PERF_COMBINED_RETRY_MULTIPLIER", "2.0"))
    retry_jitter_ratio = float(os.getenv("PERF_COMBINED_RETRY_JITTER_RATIO", "0.10"))

    sim_api.reset()
    sim_api.set_faults(drop_rate=drop_rate, delay_ms=delay_ms, corrupt_rate=0.0)

    policy = RetryPolicy(
        attempts=retry_attempts,
        initial_backoff_s=retry_initial_backoff_s,
        max_backoff_s=retry_max_backoff_s,
        multiplier=retry_multiplier,
        jitter_ratio=retry_jitter_ratio,
        retry_exceptions=(TimeoutError,),
    )

    successes = 0
    timeouts = 0
    latencies_ms = []
    retry_event_counts = []
    total_retry_events = 0
    retry_events = []

    for _ in range(attempts):
        retry_events_for_request = 0

        def _on_retry(attempt_num, exc, sleep_s):
            nonlocal retry_events_for_request, total_retry_events
            retry_events_for_request += 1
            total_retry_events += 1
            retry_events.append({
                "request_name": "REQ_PING",   # or "REQ_STATUS"
                "attempt": attempt_num,
                "sleep_s": sleep_s,
                "error": type(exc).__name__,
            })
        t0 = time.perf_counter()
        try:
            # Call request_once under retry wrapper to capture retry events
            from qaharness.utils.retry import with_retries  # local import keeps test self-contained

            rtype, payload = with_retries(
                lambda: sim_udp_perf.request_once(mt.REQ_STATUS),
                policy,
                on_retry=_on_retry,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0

            assert rtype == mt.RESP_STATE
            assert payload in (b"IDLE", b"CONFIGURED", b"STREAMING")  # defensive
            successes += 1
            latencies_ms.append(dt_ms)
            retry_event_counts.append(retry_events_for_request)

        except TimeoutError:
            timeouts += 1
            retry_event_counts.append(retry_events_for_request)

    success_rate = successes / attempts

    # Compute latency stats only for successful calls
    p50 = percentile(latencies_ms, 50) if latencies_ms else None
    p95 = percentile(latencies_ms, 95) if latencies_ms else None
    mean_ms = (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None

    # Retry behavior stats
    if retry_event_counts:
        retries_per_request_p95 = percentile(retry_event_counts, 95)
        retries_per_request_mean = sum(retry_event_counts) / len(retry_event_counts)
    else:
        retries_per_request_p95 = 0
        retries_per_request_mean = 0.0

    # Emit artifact metrics
    metrics_recorder({
        "name": "combined_drop_and_delay_envelope",
        "faults": {
            "drop_rate": drop_rate,
            "delay_ms": delay_ms,
            "corrupt_rate": 0.0,
        },
        "samples": attempts,
        "results": {
            "successes": successes,
            "timeouts": timeouts,
            "success_rate": success_rate,
        },
        "latency_ms": {
            "count": len(latencies_ms),
            "mean": mean_ms,
            "p50": p50,
            "p95": p95,
            "min": min(latencies_ms) if latencies_ms else None,
            "max": max(latencies_ms) if latencies_ms else None,
        },
        "retry": {
            "policy": {
                "attempts": retry_attempts,
                "initial_backoff_s": retry_initial_backoff_s,
                "max_backoff_s": retry_max_backoff_s,
                "multiplier": retry_multiplier,
                "jitter_ratio": retry_jitter_ratio,
            },
            "total_retry_events": total_retry_events,
            "retries_per_request_mean": retries_per_request_mean,
            "retries_per_request_p95": retries_per_request_p95,
            "events": retry_events,
        },
        "thresholds": {
            "min_success_rate": min_success_rate,
            "p50_min_ms": p50_min_ms,
            "p95_max_ms": p95_max_ms,
        },
    })

    # --- Assertions ---
    assert success_rate >= min_success_rate, (
        f"combined-fault success too low: {success_rate:.2%} "
        f"(samples={attempts}, drop={drop_rate}, delay_ms={delay_ms})"
    )

    # If there were no successes, fail clearly (above assertion may already fail, but be explicit)
    assert latencies_ms, "No successful responses recorded; cannot evaluate latency envelope"

    assert p50 is not None and p50 >= p50_min_ms, (
        f"combined p50 too low: {p50:.1f}ms "
        f"(expected >= {p50_min_ms}ms; delay fault may not be applied)"
    )

    assert p95 is not None and p95 <= p95_max_ms, (
        f"combined p95 too high: {p95:.1f}ms "
        f"(threshold {p95_max_ms}ms; consider tuning samples/retry policy/fault levels)"
    )


