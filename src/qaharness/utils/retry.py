from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class RetryPolicy:
    attemps: int = 3
    base_delay_s: float = 0.05
    max_delay_s: float = 0.25

def with_retires(fn: Callable[[], T], policy: RetryPolicy) -> T:
    last_exc: Exception | None = None
    delay = policy.base_delay_s
    for _ in range(policy.attemps):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            time.sleep(delay)
            delay = min(policy.max_delay_s, delay * 2)
    assert last_exc is not None
    raise last_exc

