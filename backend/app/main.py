import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import dashboard, events, machines, owners, plans, sim, telemetry
from app.approval.sweep import sweep_loop
from app.config import get_settings
from app.security import require_token


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    interval = get_settings().approval_sweep_interval_s
    task = asyncio.create_task(sweep_loop(interval)) if interval > 0 else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="SPANDAN API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Drop the echoed input: it can contain NaN/Infinity, which can't be JSON-encoded
    # and would otherwise turn a 422 into a 500.
    errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors})


api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])
api.include_router(owners.router)
api.include_router(machines.router)
api.include_router(telemetry.router)
api.include_router(events.router)
api.include_router(plans.router)
api.include_router(dashboard.router)
api.include_router(sim.router)
app.include_router(api)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
