from __future__ import annotations
from dataclasses import dataclass
import random
import time
import asyncio
@dataclass
class FaultConfig:
    delay_ms: int = 0           # add delay before responding
    drop_rate: float = 0.0      # 0.0..1.0
    corrupt_rate: float = 0.0   # 0.0..1.0

    def apply_delay(self) -> None:
        if self.delay_ms > 0:
            asyncio.sleep(self.delay_ms / 1000.0)

    def should_drop(self) -> bool:
        return self.drop_rate > 0 and random.random() < self.drop_rate
    
    def should_corrupt(self) -> bool:
        return self.corrupt_rate > 0 and random.random() < self.corrupt_rate
    
