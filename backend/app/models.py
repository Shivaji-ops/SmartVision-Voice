"""Database models.

All datetimes are stored as naive UTC. Schedules are stored as local wall-clock
times ("08:30") and interpreted in the patient's own timezone.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Caregiver(Base):
    __tablename__ = "caregivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    patients: Mapped[list["Patient"]] = relationship(back_populates="caregiver")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    caregiver_id: Mapped[int] = mapped_column(ForeignKey("caregivers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Language the wearer hears prompts in, as a short code: en, te, hi, ...
    language: Mapped[str] = mapped_column(String(8), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # Bumped every time a voice prompt is published; devices sync on it.
    prompt_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    caregiver: Mapped[Caregiver] = relationship(back_populates="patients")
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="patient", order_by="Contact.priority", cascade="all, delete-orphan"
    )
    devices: Mapped[list["Device"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    schedules: Mapped[list["MedicationSchedule"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )


class Contact(Base):
    """People to notify, in escalation order. Priority 1 is told first."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=1)

    patient: Mapped[Patient] = relationship(back_populates="contacts")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_seen: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    battery_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    worn: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="devices")


class MedicationSchedule(Base):
    __tablename__ = "medication_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    dose_text: Mapped[str] = mapped_column(String(200), default="")
    time_of_day: Mapped[str] = mapped_column(String(5))  # "HH:MM", patient-local
    window_minutes: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="schedules")


class Event(Base):
    """Everything the device reports, plus server-generated events like missed doses."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    device_id: Mapped[Optional[int]] = mapped_column(ForeignKey("devices.id"), nullable=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("medication_schedules.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    level: Mapped[str] = mapped_column(String(16))  # critical | warning
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | acknowledged
    tier: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_escalated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("caregivers.id"), nullable=True)

    notifications: Mapped[list["NotificationLog"]] = relationship(
        back_populates="alert", order_by="NotificationLog.id"
    )


class NotificationLog(Base):
    """One row per message the system tried to send, so escalation is auditable."""

    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    tier: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16))  # sms | voice
    target: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    alert: Mapped[Alert] = relationship(back_populates="notifications")


class VoicePrompt(Base):
    __tablename__ = "voice_prompts"
    __table_args__ = (UniqueConstraint("patient_id", "key", name="uq_prompt_patient_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))  # what the device looks up, e.g. "med_reminder"
    language: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(String(500))  # final text, in `language`
    source_text: Mapped[str] = mapped_column(String(500))  # what the caregiver typed
    source_language: Mapped[str] = mapped_column(String(8), default="en")
    is_dose_related: Mapped[bool] = mapped_column(Boolean, default=False)
    template_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class PromptAudio(Base):
    """The spoken version of a prompt, made by text to speech and cached.

    A separate table so an existing database only needs the new table, not a changed one.
    The audio counts as current while `text` and `language` match the prompt.
    """

    __tablename__ = "prompt_audio"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("voice_prompts.id"), unique=True, index=True)
    text: Mapped[str] = mapped_column(String(1000))
    language: Mapped[str] = mapped_column(String(8))
    voice: Mapped[str] = mapped_column(String(120))  # which voice settings made it
    mime: Mapped[str] = mapped_column(String(32), default="audio/wav")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
