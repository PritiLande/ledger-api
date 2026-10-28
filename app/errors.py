"""Application errors and the handlers that give every error the same JSON shape:

    {"error": {"code": "SOME_CODE", "message": "...", "details": [...]}}
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class AccountNotFound(AppError):
    status_code = 404
    code = "ACCOUNT_NOT_FOUND"


class TransactionNotFound(AppError):
    status_code = 404
    code = "TRANSACTION_NOT_FOUND"


class InsufficientBalance(AppError):
    status_code = 422
    code = "INSUFFICIENT_BALANCE"


class DuplicateTransaction(AppError):
    status_code = 409
    code = "DUPLICATE_TRANSACTION"


class DuplicateTransfer(AppError):
    status_code = 409
    code = "DUPLICATE_TRANSFER"


class InvalidTransfer(AppError):
    status_code = 422
    code = "INVALID_TRANSFER"


def _body(code: str, message: str, details: list | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0]
        loc = first["loc"]
        source = loc[0]
        field = str(loc[-1]) if len(loc) > 1 else ""
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or None, "message": e["msg"]}
            for e in errors
        ]

        if source == "query":
            status = 400
            if field == "type":
                code, message = "INVALID_TRANSACTION_TYPE", "Filter type must be 'credit' or 'debit'."
            elif field in ("page", "limit"):
                code, message = "INVALID_PAGINATION", "Invalid pagination parameters."
            else:
                code, message = "INVALID_QUERY", "Invalid query parameters."
        elif source == "path":
            status, code, message = 400, "INVALID_ACCOUNT_ID", "Invalid ID in request path."
        else:
            status = 422
            if first["type"] == "json_invalid" or len(loc) == 1:
                code, message = "INVALID_REQUEST_BODY", "Request body is missing or is not valid JSON."
            elif field == "type":
                code, message = "INVALID_TRANSACTION_TYPE", "Transaction type must be 'credit' or 'debit'."
            elif field == "amount":
                code, message = "INVALID_AMOUNT", "Amount must be greater than 0 with at most 2 decimal places."
            else:
                code, message = "VALIDATION_ERROR", "Request validation failed."
        return JSONResponse(_body(code, message, details), status_code=status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        code = codes.get(exc.status_code, "HTTP_ERROR")
        message = str(exc.detail)
        if exc.status_code == 405:
            message = "Method not allowed. Ledger entries are immutable: they can only be created and read."
        return JSONResponse(_body(code, message), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # Details are deliberately not leaked to the client.
        return JSONResponse(_body("INTERNAL_ERROR", "An unexpected error occurred."), status_code=500)
