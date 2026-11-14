from __future__ import annotations
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message); self.status, self.code, self.message, self.extra = status, code, message, extra


def _body(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


def install(app) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(_body(e.code, e.message, **e.extra), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        errs = [{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]} for err in e.errors()]
        return JSONResponse(_body("validation_error", "The request did not match the expected schema.", fields=errs), status_code=422)
