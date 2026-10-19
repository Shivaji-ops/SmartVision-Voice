import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers tables)
from .config import settings
from .db import Base, SessionLocal, engine
from .escalation import escalate_pending, sweep_missed_doses
from .models import utcnow
from .routes_caregiver import router as caregiver_router
from .routes_device import router as device_router

logger = logging.getLogger("smartvision")


def run_sweep() -> None:
    """One pass: flag missed doses, then move overdue critical alerts up a tier."""
    with SessionLocal() as db:
        now = utcnow()
        sweep_missed_doses(db, now)
        escalate_pending(db, now)
        db.commit()


async def _sweeper() -> None:
    while True:
        try:
            await asyncio.to_thread(run_sweep)
        except Exception:
            logger.exception("Sweep failed")
        await asyncio.sleep(settings.sweep_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(_sweeper())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Smart Vision API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(caregiver_router)
app.include_router(device_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
