"""FastAPI アプリ（Kong AI Sanitizer 互換エンドポイント）。

レスポンスは UTF-8 / ensure_ascii=False（Starlette JSONResponse 既定）。
バリデーション失敗・一般例外は公式互換の 400 {"error": "..."} に整形する。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .pii import do_sanitize_credentials, do_sanitize_pii
from .validation import (
    ValidationError,
    validate_rpc_request,
    validate_sanitize_request,
)

logger = logging.getLogger("tanuki_pii")

RPC_PREFIX = "llm.v1."


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時に Analyzer を構築（重いので1回）。テストでは事前に app.state.analyzer を差し込める。
    if getattr(app.state, "analyzer", None) is None:
        from .analyzer import PiiAnalyzer

        app.state.analyzer = PiiAnalyzer()
    yield


app = FastAPI(title="tanuki-pii", lifespan=lifespan)


def _error(message, status=400):
    return JSONResponse(status_code=status, content={"error": str(message)})


def _analyzer(request: Request):
    return request.app.state.analyzer


@app.get("/llm/v1/status")
async def status(request: Request):
    analyzer = _analyzer(request)
    return {
        "status": "ok",
        "supported_languages": sorted(analyzer.supported_languages),
    }


@app.post("/llm/v1/sanitize")
async def sanitize(request: Request):
    try:
        body = await request.json()
        data = validate_sanitize_request(body)
        result = await run_in_threadpool(do_sanitize_pii, data, _analyzer(request))
        return result
    except ValidationError as e:
        return _error(e)
    except Exception as e:
        logger.exception("sanitize error")
        return _error(e)


@app.post("/llm/v1/sanitize_credentials")
async def sanitize_credentials(request: Request):
    try:
        body = await request.json()
        result = await run_in_threadpool(
            do_sanitize_credentials, body, _analyzer(request)
        )
        return result
    except Exception as e:
        logger.exception("sanitize_credentials error")
        return _error(e)


@app.post("/")
async def dispatch_rpc(request: Request):
    try:
        data = await request.json()
    except Exception:
        return _error("Invalid request: no request body")

    ok, err = validate_rpc_request(data)
    if not ok:
        return _error(err)

    params = data.get("params")
    rpc_id = data.get("id")
    method = data.get("method")
    analyzer = _analyzer(request)

    try:
        if method == RPC_PREFIX + "sanitizePrompt":
            validated = validate_sanitize_request(params)
            result = await run_in_threadpool(do_sanitize_pii, validated, analyzer)
            return {"jsonrpc": "2.0", "result": result, "id": rpc_id}
        elif method == RPC_PREFIX + "sanitize_credentials":
            result = await run_in_threadpool(
                do_sanitize_credentials, params, analyzer
            )
            return {"jsonrpc": "2.0", "result": result, "id": rpc_id}
        else:
            return _error("Invalid method")
    except ValidationError as e:
        return _error(e)
    except Exception as e:
        logger.exception("rpc error")
        return _error(e)
