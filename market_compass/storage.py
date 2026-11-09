"""Local SQLite snapshots: retain the evidence used by each completed trial."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class RunStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    product_version TEXT NOT NULL, snapshot TEXT NOT NULL)""")
                yield connection
        finally:
            connection.close()

    def save(self, comparison):
        run = dict(comparison, id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat())
        snapshot = json.dumps(run, ensure_ascii=False, allow_nan=False)
        with self.connect() as connection:
            connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?)",
                               (run["id"], run["created_at"], run["product"]["version"], snapshot))
        return json.loads(snapshot)

    def list(self):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, created_at, product_version FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]

    def get(self, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT snapshot FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["snapshot"]) if row else None
