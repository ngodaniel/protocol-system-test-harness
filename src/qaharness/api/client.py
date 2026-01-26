from __future__ import annotations
import httpx

class SimApiClient:
    def __init__(self, base_url: str, timeout_s: float = 2.0):
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict:
        r = self._client.get("/health")
        r.raise_for_status()
        return r.json()

    def status(self) -> dict:
        r = self._client.get("/status")
        r.raise_for_status()
        return r.json()
    
    def reset(self) -> dict:
        r = self._client.post("/control/reset")
        r.raise_for_status()
        return r.json()
    
    def configure(self) -> dict:
        r= self._client.post("/control/configure")
        r.raise_for_status()
        return r.json()
    
    def start_stream(self) -> dict:
        r = self._client.post("/control/stream/start")
        r.raise_for_status()
        return r.json()
    
    def stop_stream(self) -> dict:
        r = self._client.post("/control/stream/stop")
        r.raise_for_status()
        return r.json()
    
    def set_faults(self, *, delay_ms: int = 0, drop_rate: float = 0.0, corrupt_rate: float = 0.0) -> dict:
        r = self._client.post("/control/faults", json={
            "delay_ms": delay_ms,
            "drop_rate": drop_rate,
            "corrupt_rate": corrupt_rate,
        })
        r.raise_for_status()
        return r.json()
    
    

