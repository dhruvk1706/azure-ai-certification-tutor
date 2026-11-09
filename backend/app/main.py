import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.assessment.api import router as assessment_router
from app.learning.api import router as learning_router
from app.learning.llm import LLMError
from app.sandbox.api import router as sandbox_router

log = logging.getLogger(__name__)

app = FastAPI(title="Azure AI Certification Tutor")

# ponytail: local origins only, matching the local-only Compose setup. Make this
# configurable when the frontend is deployed anywhere else.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(learning_router)
app.include_router(assessment_router)
app.include_router(sandbox_router)


@app.exception_handler(LLMError)
def handle_llm_error(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse({"detail": exc.message, "code": exc.code}, exc.status_code)


@app.exception_handler(SQLAlchemyError)
def handle_database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    log.error("Database error: %s", exc)
    return JSONResponse(
        {
            "detail": "The database is unavailable, or migrations have not been applied.",
            "code": "database_unavailable",
        },
        503,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
