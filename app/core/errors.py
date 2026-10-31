"""
에러 출력 양식 통일: {"error": {"code": ..., "message": ...}}
프론트 lib/api.ts 의 ApiErrorBody 가 이 형식을 읽음.

기능 코드에서는 이렇게만 쓰면 됨:
    from app.core.errors import AppError
    raise AppError("no_data", "해당 기준일의 재고 기록이 없습니다", status=404)
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger("app")


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _body(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, e: AppError):
        return _body(e.code, e.message, e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        msgs = [f"{'.'.join(str(x) for x in err['loc'][1:])}: {err['msg']}" for err in e.errors()]
        return _body("invalid_input", "; ".join(msgs) or "입력값 오류", 422)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, e: HTTPException):
        return _body(f"http_{e.status_code}", str(e.detail), e.status_code)

    @app.exception_handler(Exception)
    async def _unknown(_: Request, e: Exception):
        log.exception("unhandled error")
        return _body("internal", f"{type(e).__name__}: {e}", 500)
