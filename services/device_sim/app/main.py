import asyncio
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.device_sim.app.core.protocol import SimModel
from services.device_sim.app.core.state import DeviceState

HTTP_HOST = os.getenv("SIM_HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("SIM_HTTP_PORT", "8000"))

UDP_HOST = os.getenv("SIM_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("SIM_UDP_PORT", "9000"))

app = FastAPI(title="Device Simulator", version="0.2.0")
MODEL = SimModel()

class FaultsIn(BaseModel):
    delay_ms: int = Field(0, ge=0, le=5000)
    drop_rate: float = Field(0.0, ge=0.0, le=1.0)
    corrupt_rate: float = Field(0.0, ge=0.0, le=1.0)

@app.get("/health")
def health():
    return {"status": "ok", "state": MODEL.state.value}

@app.get("/status")
def status():
    return {
        "state": MODEL.state.value,
        "reset_count": MODEL.reset_count,
        "faults": {
            "delay_ms": MODEL.faults.delay_ms,
            "drop_rate": MODEL.faults.drop_rate,
            "corrupt_rate": MODEL.faults.corrupt_rate,
        },
    }

@app.post("/control/reset")
def reset():
    MODEL.reset()
    return {"status": "reset", "reset_count": MODEL.reset_count, "state": MODEL.state.value}

@app.post("/control/configure")
def configure():
    try:
        MODEL.configure()
        return {"status": "configured", "state": MODEL.state.value}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/control/stream/start")
def start_stream():
    try:
        MODEL.start_stream()
        return {"status": "streaming", "state": MODEL.state.value}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/control/stream/stop")
def stop_stream():
    try:
        MODEL.stop_stream()
        return {"status": "stopped", "state": MODEL.state.value}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/control/faults")
def set_faults(f: FaultsIn):
    MODEL.faults.delay_ms = f.delay_ms
    MODEL.faults.drop_rate = f.drop_rate
    MODEL.faults.corrupt_rate = f.corrupt_rate
    return {"status": "faults_updated", "faults": f.model_dump()}

class UdpProto(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr):
        # Apply delay first (simulates slow device)
        MODEL.faults.apply_delay()

        # Drop packet (simulates loss)
        if MODEL.faults.should_drop():
            return

        msg = data.decode("utf-8", errors="ignore").strip()

        # Gate UDP behavior by state to make it realistic
        if msg == "PING":
            resp = b"PONG"
        elif msg == "STATUS":
            resp = f"STATE={MODEL.state.value}".encode("utf-8")
        elif msg == "START":
            # Starting stream via UDP is only allowed when CONFIGURED
            if MODEL.state != DeviceState.CONFIGURED:
                resp = b"ERR:BAD_STATE"
            else:
                MODEL.start_stream()
                resp = b"OK:STREAMING"
        elif msg == "STOP":
            if MODEL.state != DeviceState.STREAMING:
                resp = b"ERR:BAD_STATE"
            else:
                MODEL.stop_stream()
                resp = b"OK:STOPPED"
        else:
            resp = b"ERR:UNKNOWN"

        # Corrupt response (simulates bad CRC / corrupted payload)
        if MODEL.faults.should_corrupt() and len(resp) > 0:
            resp = resp[:-1] + (b"X" if resp[-1:] != b"X" else b"Y")

        self.transport.sendto(resp, addr)

@app.on_event("startup")
async def start_udp():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProto(),
        local_addr=(UDP_HOST, UDP_PORT),
    )
    app.state.udp_transport = transport

@app.on_event("shutdown")
async def stop_udp():
    t = getattr(app.state, "udp_transport", None)
    if t:
        t.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        #"services.device_sim.app.main:app", 
        host=HTTP_HOST, 
        port=HTTP_PORT, 
        reload=False)
