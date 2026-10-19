"""Request and response shapes."""
import datetime as dt
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _as_utc_iso(value: dt.datetime) -> str:
    # The database holds naive UTC; send it with an explicit Z so browsers
    # do not read it as local time.
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[dt.datetime, PlainSerializer(_as_utc_iso, return_type=str)]

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

# Event types a device is allowed to send. "med_missed" is server-generated only.
DeviceEventType = Literal[
    "fall_confirmed",
    "fall_suppressed",
    "fall_cancelled",
    "sos",
    "med_taken",
    "med_mismatch",
    "obstacle",
    "location",
]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth -----------------------------------------------------------------
class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CaregiverOut(ORM):
    id: int
    email: str
    name: str


# ---- patients -------------------------------------------------------------
class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=32)
    priority: int = Field(default=1, ge=1, le=3)


class ContactOut(ORM):
    id: int
    name: str
    phone: str
    priority: int


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    language: str = Field(default="en", min_length=2, max_length=8)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)


class PatientOut(ORM):
    id: int
    name: str
    language: str
    timezone: str
    prompt_version: int
    contacts: list[ContactOut] = []


# ---- devices --------------------------------------------------------------
class DeviceIn(BaseModel):
    name: str = Field(default="Smart Vision frame", min_length=1, max_length=120)


class DeviceOut(ORM):
    id: int
    name: str
    last_seen: Optional[UTCDateTime] = None
    battery_pct: Optional[int] = None
    worn: bool = False


class DeviceCreatedOut(DeviceOut):
    api_key: str  # shown exactly once


class HeartbeatIn(BaseModel):
    battery_pct: Optional[int] = Field(default=None, ge=0, le=100)
    worn: Optional[bool] = None


# ---- medication -----------------------------------------------------------
class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dose_text: str = Field(default="", max_length=200)
    time_of_day: str = Field(pattern=TIME_PATTERN)
    window_minutes: int = Field(default=30, ge=5, le=240)
    active: bool = True


class SchedulePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    dose_text: Optional[str] = Field(default=None, max_length=200)
    time_of_day: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    window_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    active: Optional[bool] = None


class ScheduleOut(ORM):
    id: int
    name: str
    dose_text: str
    time_of_day: str
    window_minutes: int
    active: bool


class DoseStatusOut(BaseModel):
    schedule_id: int
    name: str
    dose_text: str
    due: str  # patient-local "HH:MM"
    status: Literal["upcoming", "pending", "taken", "missed"]


# ---- events and alerts ----------------------------------------------------
class EventIn(BaseModel):
    type: DeviceEventType
    occurred_at: Optional[dt.datetime] = None
    schedule_id: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventOut(ORM):
    id: int
    type: str
    payload: dict[str, Any]
    schedule_id: Optional[int] = None
    occurred_at: UTCDateTime


class NotificationOut(ORM):
    tier: int
    channel: str
    target: str
    created_at: UTCDateTime


class AlertOut(ORM):
    id: int
    patient_id: int
    level: str
    title: str
    status: str
    tier: int
    created_at: UTCDateTime
    acknowledged_at: Optional[UTCDateTime] = None
    notifications: list[NotificationOut] = []


# ---- voice prompts --------------------------------------------------------
class PromptIn(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    text: str = Field(default="", max_length=500)
    source_language: str = Field(default="en", min_length=2, max_length=8)
    is_dose_related: bool = False
    # Required when is_dose_related: which verified template to use.
    template_key: Optional[str] = Field(default=None, max_length=64)
    # Required when the text is written in a language other than the wearer's: the
    # wording the caregiver reviewed (from /prompts/preview, possibly edited by them).
    # Machine translation is never saved without it.
    translated_text: Optional[str] = Field(default=None, max_length=1000)


class PromptPreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    source_language: str = Field(default="en", min_length=2, max_length=8)
    # Send the caregiver's edited wording to get a fresh back-translation of it
    # without translating the original again.
    translated_text: Optional[str] = Field(default=None, max_length=1000)


class PromptPreviewOut(BaseModel):
    needs_translation: bool
    source_language: str
    target_language: str
    source_text: str
    translated_text: str
    # The translation turned back into the caregiver's language, as a sanity check.
    back_translation: Optional[str] = None


class PromptOut(ORM):
    id: int
    key: str
    language: str
    text: str
    source_text: str
    source_language: str
    is_dose_related: bool
    template_key: Optional[str] = None
    version: int
    updated_at: UTCDateTime
    # True when the spoken version exists for the present wording.
    audio_ready: bool = False
    # Set only on the reply to saving: why the voice could not be made (the text is still saved).
    audio_error: Optional[str] = None


class SpeechPreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class DevicePromptsOut(BaseModel):
    version: int
    language: str
    prompts: list[PromptOut]


class TemplateOut(BaseModel):
    key: str
    description: str
    verified_languages: list[str]


# ---- dashboard summary ----------------------------------------------------
class DeviceStatusOut(BaseModel):
    id: int
    name: str
    online: bool
    last_seen: Optional[UTCDateTime] = None
    battery_pct: Optional[int] = None
    worn: bool


class LocationOut(BaseModel):
    lat: float
    lon: float
    at: UTCDateTime


class SummaryOut(BaseModel):
    patient: PatientOut
    device: Optional[DeviceStatusOut] = None
    open_alerts: int
    doses: list[DoseStatusOut]
    last_location: Optional[LocationOut] = None
    recent_events: list[EventOut]
