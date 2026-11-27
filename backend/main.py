# ============================================================
# FastAPI 应用入口与统一异常处理
#
# 功能说明：
# 1. 创建 FastAPI v0.1.2 应用实例并注册业务路由
# 2. 集成用户认证、成果与需求发布及查询接口
# 3. 提供匹配任务状态查询及数据库健康检查
# 4. 统一处理 HTTP 错误和 Pydantic 参数校验错误
# 5. 按照数据 API 契约返回 code、message、data 结构
# 6. 自定义 OpenAPI 文档，规范 422 及认证错误示例
# 7. 通过 /docs 提供 Swagger 接口测试与联调入口
#
# 接口基础路径：/api/v1
# ============================================================

import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import router as auth_router
from backend.routers.achievements import router as achievements_router
from backend.routers.demands import router as demands_router
from backend.routers.intents import router as intents_router
from backend.routers.matches import router as matches_router
from backend.routers.pipeline_runs import router as pipeline_runs_router
from backend.routers.publishing import router as publishing_router
from backend.routers.tags import router as tags_router
from backend.routers.taxonomy import router as taxonomy_router
from backend.database import get_db

app = FastAPI(
    title="Academia-Industry Match API",
    version="0.1.2",
)

app.include_router(auth_router)
app.include_router(publishing_router)
app.include_router(pipeline_runs_router)
app.include_router(achievements_router)
app.include_router(demands_router)
app.include_router(tags_router)
app.include_router(taxonomy_router)
app.include_router(matches_router)
app.include_router(intents_router)

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


logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def internal_exception_handler(
    request: Request,
    exc: Exception,
):
    logger.exception(
        "Unhandled error: %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    return JSONResponse(
        status_code=500,
        content={
            "code": 50001,
            "message": "Internal server error",
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
