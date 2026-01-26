import asyncio
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.device_sim.app.core.protocol import SimModel
from services.device_sim.app.core.state import DeviceState
from qaharness.transport.framing import encode_frame, decode_frame, FrameError
from qaharness.transport import msgtypes as mt

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
    def connection_made(self, transport):
        # required: stored transport for later tosend()
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        loop = asyncio.get_running_loop()

        # drop packet
        if MODEL.faults.drop_rate > 0:
            import random
            if random.random() < MODEL.faults.drop_rate:
                return

        # decode request frame
        try:
            req = decode_frame(data)
        except FrameError:
            # if request is unframed/corrupt, ignore (device would drop)
            return

        # determine response
        if req.msg_type == mt.REQ_PING:
            resp_type, payload = mt.RESP_OK, b"PONG"
        elif req.msg_type == mt.REQ_STATUS:
            resp_type, payload = mt.RESP_STATE, f"{MODEL.state.value}".encode()
        elif req.msg_type == mt.REQ_START:
            if MODEL.state != DeviceState.CONFIGURED:
                resp_type, payload = mt.RESP_ERR, b"BAD_STATE"
            else:
                # prepare response FIRST
                resp_type, payload = mt.RESP_OK, b"STREAMING"
                # mutate state AFTER response is decided
                MODEL.start_stream()
        elif req.msg_type == mt.REQ_STOP:
            if MODEL.state != DeviceState.STREAMING:
                resp_type, payload = mt.RESP_ERR, b"BAD_STATE"
            else:
                resp_type, payload = mt.RESP_OK, b"STOPPED"
                MODEL.stop_stream()
        else:
            resp_type, payload = mt.RESP_ERR, b"UNKNOWN_REQ"

        resp_pkt = encode_frame(resp_type, payload)

        # corrupt response AFTER ENCODING (forces CRC mismatch)
        if MODEL.faults.corrupt_rate > 0:
            import random
            if random.random() < MODEL.faults.corrupt_rate and len(resp_pkt) > 10:
                b = bytearray(resp_pkt)
                b[8] ^= 0xFF
                resp_pkt = bytes(b)
            
        # schedule send (with optional delay)
        delay = MODEL.faults.delay_ms / 1000.0
        if delay > 0:
            loop.call_later(delay, self.transport.sendto, resp_pkt, addr)
        else:
            self.transport.sendto(resp_pkt, addr)

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
