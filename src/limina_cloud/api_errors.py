"""Stable JSON errors for every public API route."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import LiminaError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LiminaError)
    async def handle_limina_error(_request: Request, exc: LiminaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request did not match the API contract.",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )
