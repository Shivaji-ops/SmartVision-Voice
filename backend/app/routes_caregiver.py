"""Endpoints used by the caregiver dashboard. Everything here needs a bearer token."""
import datetime as dt
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .audio import audio_for, prompts_out, speak_cached
from .config import settings
from .db import get_db
from .doses import todays_doses
from .models import (
    Alert,
    Caregiver,
    Contact,
    Device,
    Event,
    MedicationSchedule,
    Patient,
    VoicePrompt,
    utcnow,
)
from .security import (
    decode_token,
    hash_device_key,
    hash_password,
    make_token,
    new_device_key,
    verify_password,
)
from .tts import Speaker, SpeechUnavailable, get_speaker
from .translation import (
    TranslationUnavailable,
    Translator,
    get_translator,
    get_verified_template,
    list_templates,
)

router = APIRouter(prefix="/api")
_bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def current_caregiver(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)], db: DB
) -> Caregiver:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        caregiver_id = decode_token(creds.credentials)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session expired. Sign in again.")
    caregiver = db.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session expired. Sign in again.")
    return caregiver


Me = Annotated[Caregiver, Depends(current_caregiver)]


def owned_patient(db: Session, patient_id: int, me: Caregiver) -> Patient:
    patient = db.get(Patient, patient_id)
    # Same answer for "missing" and "not yours", so ids cannot be probed.
    if patient is None or patient.caregiver_id != me.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    return patient


def _check_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, f"Unknown timezone: {name}")


# ---- auth -------------------------------------------------------------------
@router.post("/auth/register", response_model=schemas.TokenOut, status_code=201)
def register(body: schemas.RegisterIn, db: DB):
    email = body.email.strip().lower()
    if db.scalar(select(Caregiver.id).where(Caregiver.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    caregiver = Caregiver(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(caregiver)
    db.commit()
    return schemas.TokenOut(access_token=make_token(caregiver.id))


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginIn, db: DB):
    caregiver = db.scalar(select(Caregiver).where(Caregiver.email == body.email.strip().lower()))
    if caregiver is None or not verify_password(body.password, caregiver.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    return schemas.TokenOut(access_token=make_token(caregiver.id))


@router.get("/me", response_model=schemas.CaregiverOut)
def me(me: Me):
    return me


# ---- patients and contacts --------------------------------------------------
@router.get("/patients", response_model=list[schemas.PatientOut])
def list_patients(me: Me, db: DB):
    return db.scalars(select(Patient).where(Patient.caregiver_id == me.id).order_by(Patient.id)).all()


@router.post("/patients", response_model=schemas.PatientOut, status_code=201)
def create_patient(body: schemas.PatientIn, me: Me, db: DB):
    _check_timezone(body.timezone)
    patient = Patient(
        caregiver_id=me.id, name=body.name.strip(), language=body.language.lower(), timezone=body.timezone
    )
    db.add(patient)
    db.commit()
    return patient


@router.get("/patients/{patient_id}", response_model=schemas.PatientOut)
def get_patient(patient_id: int, me: Me, db: DB):
    return owned_patient(db, patient_id, me)


@router.post("/patients/{patient_id}/contacts", response_model=schemas.ContactOut, status_code=201)
def add_contact(patient_id: int, body: schemas.ContactIn, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    contact = Contact(patient_id=patient.id, name=body.name.strip(), phone=body.phone.strip(), priority=body.priority)
    db.add(contact)
    db.commit()
    return contact


@router.delete("/patients/{patient_id}/contacts/{contact_id}", status_code=204)
def delete_contact(patient_id: int, contact_id: int, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    contact = db.get(Contact, contact_id)
    if contact is None or contact.patient_id != patient.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
    db.delete(contact)
    db.commit()


# ---- devices ----------------------------------------------------------------
@router.get("/patients/{patient_id}/devices", response_model=list[schemas.DeviceOut])
def list_devices(patient_id: int, me: Me, db: DB):
    return owned_patient(db, patient_id, me).devices


@router.post("/patients/{patient_id}/devices", response_model=schemas.DeviceCreatedOut, status_code=201)
def create_device(patient_id: int, body: schemas.DeviceIn, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    key = new_device_key()
    device = Device(patient_id=patient.id, name=body.name.strip(), key_hash=hash_device_key(key))
    db.add(device)
    db.commit()
    return schemas.DeviceCreatedOut(
        id=device.id, name=device.name, last_seen=None, battery_pct=None, worn=False, api_key=key
    )


# ---- medication schedules ---------------------------------------------------
@router.get("/patients/{patient_id}/schedules", response_model=list[schemas.ScheduleOut])
def list_schedules(patient_id: int, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    return sorted(patient.schedules, key=lambda s: s.time_of_day)


@router.post("/patients/{patient_id}/schedules", response_model=schemas.ScheduleOut, status_code=201)
def create_schedule(patient_id: int, body: schemas.ScheduleIn, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    sched = MedicationSchedule(patient_id=patient.id, **body.model_dump())
    db.add(sched)
    db.commit()
    return sched


def _owned_schedule(db: Session, schedule_id: int, me: Caregiver) -> MedicationSchedule:
    sched = db.get(MedicationSchedule, schedule_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")
    owned_patient(db, sched.patient_id, me)
    return sched


@router.patch("/schedules/{schedule_id}", response_model=schemas.ScheduleOut)
def update_schedule(schedule_id: int, body: schemas.SchedulePatch, me: Me, db: DB):
    sched = _owned_schedule(db, schedule_id, me)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sched, field, value)
    db.commit()
    return sched


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, me: Me, db: DB):
    sched = _owned_schedule(db, schedule_id, me)
    db.delete(sched)
    db.commit()


# ---- events and summary -----------------------------------------------------
@router.get("/patients/{patient_id}/events", response_model=list[schemas.EventOut])
def list_events(
    patient_id: int,
    me: Me,
    db: DB,
    limit: int = Query(50, ge=1, le=200),
    type: Optional[str] = None,
):
    patient = owned_patient(db, patient_id, me)
    query = select(Event).where(Event.patient_id == patient.id)
    if type:
        query = query.where(Event.type == type)
    return db.scalars(query.order_by(Event.occurred_at.desc(), Event.id.desc()).limit(limit)).all()


@router.get("/patients/{patient_id}/summary", response_model=schemas.SummaryOut)
def summary(patient_id: int, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    now = utcnow()

    device_status = None
    if patient.devices:
        device = max(patient.devices, key=lambda d: d.last_seen or dt.datetime.min)
        online = bool(
            device.last_seen
            and (now - device.last_seen).total_seconds() <= settings.device_online_seconds
        )
        device_status = schemas.DeviceStatusOut(
            id=device.id,
            name=device.name,
            online=online,
            last_seen=device.last_seen,
            battery_pct=device.battery_pct,
            worn=device.worn,
        )

    open_alerts = len(
        db.scalars(select(Alert.id).where(Alert.patient_id == patient.id, Alert.status == "open")).all()
    )

    last_location = None
    loc = db.scalar(
        select(Event)
        .where(Event.patient_id == patient.id, Event.type == "location")
        .order_by(Event.occurred_at.desc())
        .limit(1)
    )
    if loc and "lat" in loc.payload and "lon" in loc.payload:
        last_location = schemas.LocationOut(
            lat=float(loc.payload["lat"]), lon=float(loc.payload["lon"]), at=loc.occurred_at
        )

    recent = db.scalars(
        select(Event)
        .where(Event.patient_id == patient.id, Event.type != "location")
        .order_by(Event.occurred_at.desc(), Event.id.desc())
        .limit(12)
    ).all()

    return schemas.SummaryOut(
        patient=schemas.PatientOut.model_validate(patient),
        device=device_status,
        open_alerts=open_alerts,
        doses=[schemas.DoseStatusOut(**row) for row in todays_doses(db, patient, now)],
        last_location=last_location,
        recent_events=[schemas.EventOut.model_validate(e) for e in recent],
    )


# ---- alerts -----------------------------------------------------------------
@router.get("/alerts", response_model=list[schemas.AlertOut])
def list_alerts(
    me: Me,
    db: DB,
    state: Literal["open", "acknowledged", "all"] = "open",
    limit: int = Query(50, ge=1, le=200),
):
    patient_ids = db.scalars(select(Patient.id).where(Patient.caregiver_id == me.id)).all()
    query = select(Alert).where(Alert.patient_id.in_(patient_ids))
    if state != "all":
        query = query.where(Alert.status == state)
    return db.scalars(query.order_by(Alert.created_at.desc()).limit(limit)).all()


@router.post("/alerts/{alert_id}/ack", response_model=schemas.AlertOut)
def acknowledge_alert(alert_id: int, me: Me, db: DB):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found.")
    owned_patient(db, alert.patient_id, me)
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by_id = me.id
        db.commit()
    return alert


# ---- voice prompts ----------------------------------------------------------
@router.get("/dose-templates", response_model=list[schemas.TemplateOut])
def dose_templates(me: Me):
    return list_templates()


@router.get("/patients/{patient_id}/prompts", response_model=list[schemas.PromptOut])
def list_prompts(patient_id: int, me: Me, db: DB):
    patient = owned_patient(db, patient_id, me)
    prompts = db.scalars(
        select(VoicePrompt).where(VoicePrompt.patient_id == patient.id).order_by(VoicePrompt.key)
    ).all()
    return prompts_out(db, prompts)


def _wav(data: bytes) -> Response:
    return Response(content=data, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/patients/{patient_id}/speech/preview")
def speech_preview(
    patient_id: int,
    body: schemas.SpeechPreviewIn,
    me: Me,
    db: DB,
    speaker: Annotated[Speaker, Depends(get_speaker)],
):
    """Speak some text in the wearer's language without saving anything, so it can be heard first."""
    patient = owned_patient(db, patient_id, me)
    try:
        return _wav(speak_cached(speaker, body.text, patient.language))
    except SpeechUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.get("/patients/{patient_id}/prompts/{key}/audio")
def prompt_audio(
    patient_id: int,
    key: str,
    me: Me,
    db: DB,
    speaker: Annotated[Speaker, Depends(get_speaker)],
):
    """The spoken version of a saved prompt. Made now if it is missing, which also retries a failed save."""
    patient = owned_patient(db, patient_id, me)
    prompt = db.scalar(select(VoicePrompt).where(VoicePrompt.patient_id == patient.id, VoicePrompt.key == key))
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt not found.")
    try:
        return _wav(audio_for(db, prompt, speaker).data)
    except SpeechUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.post("/patients/{patient_id}/prompts/preview", response_model=schemas.PromptPreviewOut)
def preview_prompt(
    patient_id: int,
    body: schemas.PromptPreviewIn,
    me: Me,
    db: DB,
    translator: Annotated[Translator, Depends(get_translator)],
):
    """Translate without saving, so the caregiver can read the result before it goes anywhere."""
    patient = owned_patient(db, patient_id, me)
    source = body.source_language.lower()
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Enter the prompt text.")
    if source == patient.language:
        return schemas.PromptPreviewOut(
            needs_translation=False,
            source_language=source,
            target_language=patient.language,
            source_text=text,
            translated_text=text,
        )
    try:
        translated = (body.translated_text or "").strip() or translator.translate(text, source, patient.language)
        back = translator.translate(translated, patient.language, source)
    except TranslationUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return schemas.PromptPreviewOut(
        needs_translation=True,
        source_language=source,
        target_language=patient.language,
        source_text=text,
        translated_text=translated,
        back_translation=back,
    )


@router.post("/patients/{patient_id}/prompts", response_model=schemas.PromptOut)
def publish_prompt(
    patient_id: int,
    body: schemas.PromptIn,
    me: Me,
    db: DB,
    speaker: Annotated[Speaker, Depends(get_speaker)],
):
    patient = owned_patient(db, patient_id, me)

    if body.is_dose_related:
        # Dose wording is never machine translated. Use a reviewed template or refuse.
        if not body.template_key:
            raise HTTPException(
                422,
                "Prompts about taking medicine must use a reviewed template. Choose one.",
            )
        final_text = get_verified_template(body.template_key, patient.language)
        if final_text is None:
            raise HTTPException(
                422,
                f"No reviewed '{body.template_key}' template exists in '{patient.language}' yet. "
                "Dose prompts are not machine translated.",
            )
        source_text = final_text
    else:
        source_text = body.text.strip()
        if not source_text:
            raise HTTPException(422, "Enter the prompt text.")
        if body.source_language.lower() == patient.language:
            final_text = source_text
        else:
            # Machine output is saved only after a caregiver has seen it. The dashboard gets
            # it from /prompts/preview, and sends back what they approved or edited.
            final_text = (body.translated_text or "").strip()
            if not final_text:
                raise HTTPException(422, "Translate the message and check the result before saving it.")

    patient.prompt_version += 1
    prompt = db.scalar(
        select(VoicePrompt).where(VoicePrompt.patient_id == patient.id, VoicePrompt.key == body.key)
    )
    if prompt is None:
        prompt = VoicePrompt(patient_id=patient.id, key=body.key)
        db.add(prompt)
    prompt.language = patient.language
    prompt.text = final_text
    prompt.source_text = source_text
    prompt.source_language = body.source_language.lower()
    prompt.is_dose_related = body.is_dose_related
    prompt.template_key = body.template_key if body.is_dose_related else None
    prompt.version = patient.prompt_version
    prompt.updated_at = utcnow()
    db.commit()

    # The wording is saved either way. If the voice cannot be made now, say why; it is
    # made again when the glasses or the dashboard ask for it.
    audio_error = None
    try:
        audio_for(db, prompt, speaker)
    except SpeechUnavailable as exc:
        audio_error = str(exc)
    result = prompts_out(db, [prompt])[0]
    result.audio_error = audio_error
    return result
