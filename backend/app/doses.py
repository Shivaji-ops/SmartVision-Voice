"""Dose windows and per-day status.

A dose is "taken" if a med_taken event for that schedule lands between an hour
before the due time and the end of the window. After the window closes with
no such event, it is "missed".
"""
import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event, MedicationSchedule, Patient

UTC = dt.timezone.utc
EARLY_MINUTES = 60


def _naive_utc(value: dt.datetime) -> dt.datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def dose_window(
    sched: MedicationSchedule, patient: Patient, now_utc: dt.datetime, day_offset: int = 0
) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    """Return (due_utc, end_utc, due_local) for the patient's local day + offset."""
    tz = ZoneInfo(patient.timezone)
    local_now = now_utc.replace(tzinfo=UTC).astimezone(tz)
    day = (local_now + dt.timedelta(days=day_offset)).date()
    hour, minute = (int(part) for part in sched.time_of_day.split(":"))
    due_local = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    end_local = due_local + dt.timedelta(minutes=sched.window_minutes)
    return _naive_utc(due_local), _naive_utc(end_local), due_local


def dose_outcome(
    db: Session, sched: MedicationSchedule, due_utc: dt.datetime, end_utc: dt.datetime
) -> str | None:
    """'taken', 'missed' (already recorded), or None if neither has happened."""
    taken = db.scalar(
        select(Event.id)
        .where(
            Event.schedule_id == sched.id,
            Event.type == "med_taken",
            Event.occurred_at >= due_utc - dt.timedelta(minutes=EARLY_MINUTES),
            Event.occurred_at <= end_utc,
        )
        .limit(1)
    )
    if taken:
        return "taken"
    missed = db.scalar(
        select(Event.id)
        .where(
            Event.schedule_id == sched.id,
            Event.type == "med_missed",
            Event.occurred_at == end_utc,
        )
        .limit(1)
    )
    return "missed" if missed else None


def todays_doses(db: Session, patient: Patient, now_utc: dt.datetime) -> list[dict]:
    rows = []
    for sched in patient.schedules:
        if not sched.active:
            continue
        due_utc, end_utc, due_local = dose_window(sched, patient, now_utc)
        outcome = dose_outcome(db, sched, due_utc, end_utc)
        if outcome:
            status = outcome
        elif now_utc < due_utc:
            status = "upcoming"
        elif now_utc <= end_utc:
            status = "pending"
        else:
            status = "missed"  # window closed; the sweeper will record it shortly
        rows.append(
            {
                "schedule_id": sched.id,
                "name": sched.name,
                "dose_text": sched.dose_text,
                "due": due_local.strftime("%H:%M"),
                "status": status,
            }
        )
    rows.sort(key=lambda r: r["due"])
    return rows
