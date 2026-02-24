from __future__ import annotations

import random
import time

from dataclasses import dataclass
from typing import Callable, TypeVar, Any

T = TypeVar("T")

@dataclass(frozen=True)
class RetryPolicy:
    """
    Retry policy for transient failures.
    
    attempts: total attemps including the first try. Must be >= 1
    
    initial_backoff_s: sleep before the 2nd attempt
    
    max_backoff_s: caps the backoff sleep
    
    multiplier: exponential growth factor (e.g. 2.0 doubles each retry)
    
    jitter_ratio: adds +/- jitter to backoff to avoid lockstep retries
        example: 0.20 means backoff is randomized in [80%, 120%]
        
    timeout_s: optional total wall-clock retry budget. if exceeded, stop retrying
    """
    attempts: int = 3
    initial_backoff_s: float = 0.05
    max_backoff_s: float = 1.0
    multiplier: float = 2.0
    jitter_ratio: float = 0.0
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,)
    timeout_s: float | None = None
    base_delay_s: float = 0.05
    max_delay_s: float = 0.25

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempt must be >= 1")
        if self.initial_backoff_s < 0:
            raise ValueError("initial_backoff_s must be >= 0")
        if self.max_backoff_s < 0:
            raise ValueError("max_backoff_s must be >= 0")
        if self.multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0")
        if not (0.0 <= self.jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        if self.timeout_s is not None and self.timeout_s < 0:
            raise ValueError("timeout_s must be >= 0 when provided")

    def backoff_for_attempt(self, attempt_index: int) -> float:
        """
        attempt_index is 1-based (1 = first attempt, no sleep before it).
        returns the sleep duration before the NEXT retry after this attempt failed
        """

        # atempt 1 -> backoff^0 = initial_backoff_s
        exp = max(0, attempt_index - 1)
        base = self.initial_backoff_s * (self.multiplier ** exp)
        sleep_s = min(base, self.max_backoff_s)

        if self.jitter_ratio > 0 and sleep_s > 0:
            low = max(0.0, 1.0 - self.jitter_ratio)
            high = 1.0 + self.jitter_ratio
            sleep_s *= random.uniform(low, high)

        return sleep_s

def with_retries(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[int, BaseException, float], Any] | None = None,
) -> T:
    """
    execute fn() with retries according to 'policy'
    
    on_retry(attempt_number, exception, sleep_s):
        optional callback invoked after a failure that will be retried.
        useful for metrics/logging
        
    raises:
        the last exception encountered (or first non-retryable exception)
    """
    start = time.perf_counter()
    last_exc: BaseException | None = None

    for attempt in range(1, policy.attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit should never be swalled
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

            # non-retryable exception type -> fail immediately
            if not isinstance(exc, policy.retry_exceptions):
                raise

            last_exc = exc

            # no more attemps left
            if attempt >= policy.attempts:
                break

            sleep_s = policy.backoff_for_attempt(attempt)

            # respect total timeout budget if provided
            if policy.timeout_s is not None:
                elapsed = time.perf_counter() - start
                remaining = policy.timeout_s - elapsed
                if remaining <= 0:
                    break

                sleep_s = min(sleep_s, remaining)

            if on_retry is not None:
                on_retry(attempt, exc, sleep_s)

            if sleep_s > 0:
                time.sleep(sleep_s)

    assert last_exc is not None     # defensive; loop always sets this before break
    raise last_exc


