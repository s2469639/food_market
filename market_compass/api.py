"""Local-only trial API. No keys, uploads, remote database, or external AI calls."""

import json
import os
from pathlib import Path
import sqlite3
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .comparison import FIXTURE, build_comparison
from .comtrade import DataError
from .storage import RunStore


ROOT = Path(__file__).resolve().parent.parent
LOCAL_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}


def create_app(database_path=None):
    app = FastAPI(title="Market Compass 로컬 연결 시험")
    store = RunStore(database_path or os.environ.get("MARKET_COMPASS_DB", ROOT / "data" / "market_compass.sqlite3"))

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if (origin and origin not in LOCAL_ORIGINS) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"detail": "로컬 화면에서만 실행할 수 있습니다."})
        return await call_next(request)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, error):
        return JSONResponse(status_code=503, content={"detail": "로컬 저장에 실패했습니다. 저장 공간과 파일 권한을 확인하세요."})

    @app.get("/api/product")
    def product():
        return json.loads(FIXTURE.read_text(encoding="utf-8"))["product"]

    @app.get("/api/runs")
    def runs():
        return store.list()

    @app.post("/api/runs", status_code=201)
    def create_run():
        try:
            comparison = build_comparison()
        except (DataError, ValueError, KeyError, OSError):
            raise HTTPException(422, "시험 자료를 읽거나 검증하지 못했습니다. 결과를 저장하지 않았습니다.") from None
        return store.save(comparison)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: UUID):
        result = store.get(str(run_id))
        if result is None:
            raise HTTPException(404, "저장된 결과를 찾을 수 없습니다.")
        return result

    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
