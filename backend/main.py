
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import router as auth_router
from backend.routers.achievements import router as achievements_router
from backend.routers.pipeline_runs import router as pipeline_runs_router
from backend.routers.publishing import router as publishing_router
from backend.database import get_db

app = FastAPI(
    title="Academia-Industry Match API",
    version="0.1.2",
)

app.include_router(auth_router)
app.include_router(publishing_router)
app.include_router(pipeline_runs_router)
app.include_router(achievements_router)

@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    codes = {
        400: 40001,
        401: 40101,
        403: 40301,
        404: 40401,
        409: 40901,
        422: 42201,
        500: 50001,
        503: 50301,
    }

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": codes.get(exc.status_code, 50001),
            "message": str(exc.detail),
            "data": None,
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=422,
        content={
            "code": 42201,
            "message": "Validation error",
            "data": None,
        },
    )


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )

    # Define the response structure required by the API contract.
    openapi_schema.setdefault("components", {}).setdefault(
        "schemas", {}
    )["APIValidationError"] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "integer",
                "const": 42201,
            },
            "message": {
                "type": "string",
            },
            "data": {
                "type": "null",
            },
        },
        "required": ["code", "message", "data"],
    }

    validation_response = {
        "description": "Request validation error",
        "content": {
            "application/json": {
                "schema": {
                    "$ref": "#/components/schemas/APIValidationError"
                },
                "example": {
                    "code": 42201,
                    "message": "Validation error",
                    "data": None,
                },
            }
        },
    }

    # Replace FastAPI's default 422 documentation.
    for path_item in openapi_schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue

            responses = operation.get("responses")
            if responses and "422" in responses:
                responses["422"] = validation_response


    # Ensure error response examples include "data": null.
    for path_item in openapi_schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue

            for status_code in ("401", "403"):
                response = operation.get("responses", {}).get(status_code)

                if response is None:
                    continue

                json_content = response.get(
                    "content", {}
                ).get("application/json", {})

                example = json_content.get("example")

                if isinstance(example, dict):
                    example["data"] = None

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
