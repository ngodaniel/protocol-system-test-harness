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

    def reset(self) -> dict:
        r = self._client.post("/control/reset")
        r.raise_for_status()
        return r.json()

