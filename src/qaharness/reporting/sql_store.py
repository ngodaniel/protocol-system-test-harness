from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

def _default_db_path() -> Path:
    p = Path(os.getenv("QA_RESULTS_DB", "artifacts/results.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass(frozen=True)
class SqlStoreConfig:
    db_path: Path

class SqlStore:
    """
    Tiny sqlite-backed telemetry store for test runs/results/perf metrics
    Thread-safe enough for local pytest usage via an internal lock
    """
    def __init__(self, config: SqlStoreConfig | None = None):
        self._cfg = config or SqlStoreConfig(db_path=_default_db_path())
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._cfg.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._cfg.db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS test_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            git_sha TEXT,
            branch TEXT,
            ci_job TEXT,
            os_name TEXT,
            python_version TEXT,
            exit_status INTEGER
        );

        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            nodeid TEXT NOT NULL,
            outcome TEXT NOT NULL,
            duration_s REAL,
            error_type TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES test_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_test_results_nodeid ON test_results(nodeid);

        CREATE TABLE IF NOT EXISTS perf_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            nodeid TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            unit TEXT,
            tags_JSON TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES test_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_perf_metrics_run_id ON perf_metrics(run_id);
        CREATE INDEX IF NOT EXISTS idx_perf_metrics_nodeid ON perf_metrics_events(nodeid);
        CREATE INDEX IF NOT EXISTS idx_perf_metrics_name ON perf_metrics(metric_name);

        CREATE TABLE IF NOT EXISTS retry_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   
            run_id TEXT NOT NULL,
            nodeid TEXT NOT NULL,
            equest_name TEXT,
            attempt_number INTEGER,
            sleep_s REAL,
            exception_type TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES test_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_retry_events_run_id ON retry_events(run_id)
        CREATE INDEX IF NOT EXISTS idx_retry_events_nodeid ON retry_events(nodeid)
        """

        with self._lock, self._conn:
            self._conn.executescript(ddl)

    def start_run(
        self,
        *,
        run_id: str,
        started_at: str,
        git_sha: str | None,
        branch: str | None,
        ci_job: str | None,
        os_name: str,
        python_version: str,
    ) -> None:
        sql = """
        INSERT INTO test_runs (
            run_id, started_at, git_sha, branch, ci_job, os_name, python_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        with self._lock, self._conn:
            self._conn.execute(
                sql,
                (run_id, started_at, git_sha, branch, ci_job, os_name, python_version),
            )
    
    def finish_run(self, *, run_id:str, finished_at: str, exit_status: int) -> None:
        sql = """
        UPDATE test_runs
        SET finished_at = ?, exit_status = ?
        WHERE run_id = ?
        """

        with self._lock, self._conn:
            self._conn.execute(sql, (finished_at, exit_status, run_id))

    def record_test_result(
        self,
        *,
        run_id: str,
        nodeid: str,
        outcome: str, 
        duration_s: float | None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        sql = """
        INSERT INTO test_results (
            run_id, nodeid, outcome, duration_s, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        with self._lock, self._conn:
            self._conn.execute(
                sql,
                (run_id, nodeid, outcome, duration_s, error_type, error_message),
            )
    
    def record_metric(
        self,
        *,
        run_id:str,
        nodeid: str,
        metric_name: str,
        metric_value: float | int | None,
        unit: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        sql = """
        INSERT INTO perf_metrics (
            run_id, nodeid, metric_name, metric_value, unit, tags_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        tags_json = json.dumps(tags, sort_keys=True) if tags else None
        val = None if metric_value is None else float(metric_value)
        with self._lock, self._conn:
            self._conn.execute(sql, (run_id, nodeid, metric_name, val, unit, tags_json))

    def record_retry_event(
        self,
        *,
        run_id: str,
        nodeid: str,
        request_name: str | None,
        attempt_number: int,
        sleep_s: float,
        exception_type: str,
    ) -> None:
        sql = """
        INSERT INTO retry_events (
            run_id, nodeid, request_name, attempt_number, sleep_s, exception_type
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        
        with self._lock, self._conn:
            self._conn.execute(sql, (run_id, nodeid, request_name, attempt_number, sleep_s, exception_type),)
    

