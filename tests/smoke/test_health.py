import os
import httpx

SIM_HTTP = os.getenv("SIM_HTTP", "http://127.0.0.1:8000")

def test_health(sim_api):
    resp = sim_api.health()
    assert resp["status"] == "ok"

