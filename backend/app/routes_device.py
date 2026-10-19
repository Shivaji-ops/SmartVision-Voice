"""Endpoints the glasses call. Authenticated by the X-Device-Key header."""
import datetime as dt
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .audio import audio_for, prompts_out
from .db import get_db
from .escalation import raise_alert
from .models import Device, Event, Patient, VoicePrompt, utcnow
from .security import hash_device_key
from .tts import Speaker, SpeechUnavailable, get_speaker

router = APIRouter(prefix="/api/device")

DB = Annotated[Session, Depends(get_db)]


def current_device(db: DB, x_device_key: Annotated[str | None, Header()] = None) -> Device:
    if not x_device_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Device-Key header.")
    device = db.scalar(select(Device).where(Device.key_hash == hash_device_key(x_device_key)))
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown device key.")
    return device


Dev = Annotated[Device, Depends(current_device)]


def _to_naive_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


@router.post("/heartbeat", status_code=204)
def heartbeat(body: schemas.HeartbeatIn, device: Dev, db: DB):
    device.last_seen = utcnow()
    if body.battery_pct is not None:
        device.battery_pct = body.battery_pct
    if body.worn is not None:
        device.worn = body.worn
    db.commit()


@router.post("/events", response_model=schemas.EventOut, status_code=201)
def ingest_event(body: schemas.EventIn, device: Dev, db: DB):
    now = utcnow()
    # Trust the device clock only if it is not in the future.
    occurred = _to_naive_utc(body.occurred_at) if body.occurred_at else now
    if occurred > now:
        occurred = now

    event = Event(
        patient_id=device.patient_id,
        device_id=device.id,
        schedule_id=body.schedule_id,
        type=body.type,
        payload=body.payload,
        occurred_at=occurred,
    )
    db.add(event)

    device.last_seen = now
    if isinstance(body.payload.get("worn"), bool):
        device.worn = body.payload["worn"]
    db.flush()

    # The device has already applied wear-state gating, so a fall_confirmed here
    # is real. fall_suppressed and fall_cancelled are recorded but never alert.
    if body.type == "fall_confirmed":
        raise_alert(db, event, "critical", "Fall detected", now)
    elif body.type == "sos":
        raise_alert(db, event, "critical", "SOS button pressed", now)

    db.commit()
    return event


@router.get("/schedule", response_model=list[schemas.ScheduleOut])
def device_schedule(device: Dev, db: DB):
    patient = db.get(Patient, device.patient_id)
    return sorted((s for s in patient.schedules if s.active), key=lambda s: s.time_of_day)


@router.get("/prompts", response_model=schemas.DevicePromptsOut)
def device_prompts(device: Dev, db: DB, since_version: int = Query(0, ge=0)):
    """Prompts changed after since_version. The device stores `version` and sends it next time."""
    patient = db.get(Patient, device.patient_id)
    prompts = db.scalars(
        select(VoicePrompt)
        .where(VoicePrompt.patient_id == patient.id, VoicePrompt.version > since_version)
        .order_by(VoicePrompt.version)
    ).all()
    return schemas.DevicePromptsOut(
        version=patient.prompt_version, language=patient.language, prompts=prompts_out(db, prompts)
    )


@router.get("/prompts/{key}/audio")
def device_prompt_audio(
    key: str,
    request: Request,
    device: Dev,
    db: DB,
    speaker: Annotated[Speaker, Depends(get_speaker)],
):
    """The spoken prompt as a WAV file. Send If-None-Match with the last ETag to skip an unchanged download."""
    prompt = db.scalar(select(VoicePrompt).where(VoicePrompt.patient_id == device.patient_id, VoicePrompt.key == key))
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such prompt.")
    try:
        data = audio_for(db, prompt, speaker).data
    except SpeechUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    etag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(content=data, media_type="audio/wav", headers={"ETag": etag})
