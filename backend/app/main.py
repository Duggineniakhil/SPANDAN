from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import events, machines, owners, sim, telemetry
from app.security import require_token

app = FastAPI(title="SPANDAN API", version="0.1.0")


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
api.include_router(sim.router)
app.include_router(api)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
