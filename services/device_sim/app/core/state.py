from enum import Enum

class DeviceState(str, Enum):
    IDLE = "IDLE"
    CONFIGURED = "CONFIGURED"
    STREAMING = "STREAMING"

    