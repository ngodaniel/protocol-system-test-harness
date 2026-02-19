from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    sim_http: str
    sim_udp_host: str
    sim_udp_port: int
    sim_tcp_host: str
    sim_tcp_port: int


def get_settings() -> Settings:
    """
    Centralized configuration for tests and harness code.
    Values come from environment variables with safe defaults.
    """
    return Settings(
        sim_http=os.getenv("SIM_HTTP", "http://127.0.0.1:8000"),
        sim_udp_host=os.getenv("SIM_UDP_HOST", "127.0.0.1"),
        sim_udp_port=int(os.getenv("SIM_UDP_PORT", "9000")),
        sim_tcp_host=os.getenv("SIM_TCP_HOST", "127.0.0.1"),
        sim_tcp_port=int(os.getenv("SIM_TCP_PORT", "9100")),
    )
