from __future__ import annotations
from dataclasses import dataclass, field
from .state import DeviceState
from .faults import FaultConfig

@dataclass
class SimModel:
    state: DeviceState = DeviceState.IDLE
    reset_count: int = 0
    faults: FaultConfig = field(default_factory=FaultConfig)

    def reset(self) -> None:
        self.state = DeviceState.IDLE
        self.reset_count += 1
        # keep faults as-is; tests can choose to reset them explicitly

    def configure(self) -> None:
        if self.state != DeviceState.IDLE:
            raise ValueError(f"Invalid transition: {self.state} -> CONFIGURED")
        self.state = DeviceState.CONFIGURED

    def start_stream(self) -> None:
        if self.state != DeviceState.CONFIGURED:
            raise ValueError(f"Invalid transition: {self.state} -> STREAMING")
        self.state = DeviceState.STREAMING

    def stop_stream(self) -> None:
        if self.state != DeviceState.STREAMING:
            raise ValueError(f"Invalid transition: {self.state} -> CONFIGURED")
        self.state = DeviceState.CONFIGURED

    