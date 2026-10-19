"""Alerts, escalation tiers and the missed-dose sweep.

Critical alerts (a confirmed fall, an SOS) start at tier 1 and move up a tier
every ESCALATION_SECONDS until a caregiver acknowledges them:

    tier 1: SMS to the priority-1 contact
    tier 2: SMS and a voice call to the priority-2 contact
    tier 3: SMS and a voice call to the priority-3 contact

Warnings (a missed dose) notify the priority-1 contact once and do not escalate.
"""
import datetime as dt
import logging
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .doses import dose_outcome, dose_window
from .models import Alert, Event, MedicationSchedule, NotificationLog, Patient

logger = logging.getLogger("smartvision.escalation")


class Notifier(Protocol):
    def send(self, channel: str, target: str, message: str) -> None: ...


class LogNotifier:
    """Development default: writes to the log instead of sending anything.

    Replace with an SMS / voice provider (Twilio, MSG91, ...) by calling
    set_notifier() at startup.
    """

    def send(self, channel: str, target: str, message: str) -> None:
        logger.warning("[%s -> %s] %s", channel, target, message)


_notifier: Notifier = LogNotifier()


def set_notifier(notifier: Notifier) -> None:
    global _notifier
    _notifier = notifier


def _notify(db: Session, alert: Alert, tier: int) -> None:
    patient = db.get(Patient, alert.patient_id)
    contact = next((c for c in patient.contacts if c.priority == tier), None)
    if contact is None:
        logger.warning("Alert %s tier %s: no contact at that priority", alert.id, tier)
        return
    message = f"Smart Vision: {patient.name} - {alert.title}"
    channels = ["sms"] if tier == 1 else ["sms", "voice"]
    for channel in channels:
        try:
            _notifier.send(channel, contact.phone, message)
        except Exception:  # a failed provider must never block the alert itself
            logger.exception("Sending %s to %s failed", channel, contact.phone)
            continue
        db.add(NotificationLog(alert_id=alert.id, tier=tier, channel=channel, target=contact.phone))


def raise_alert(
    db: Session, event: Event, level: str, title: str, now: Optional[dt.datetime] = None
) -> Alert:
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    alert = Alert(
        patient_id=event.patient_id,
        event_id=event.id,
        level=level,
        title=title,
        tier=1,
        created_at=now,
        last_escalated_at=now,
    )
    db.add(alert)
    db.flush()
    _notify(db, alert, 1)
    return alert


def escalate_pending(db: Session, now: dt.datetime) -> int:
    """Move unacknowledged critical alerts up a tier once they are overdue."""
    open_critical = db.scalars(
        select(Alert).where(
            Alert.status == "open",
            Alert.level == "critical",
            Alert.tier < settings.max_escalation_tier,
        )
    ).all()
    moved = 0
    for alert in open_critical:
        if (now - alert.last_escalated_at).total_seconds() >= settings.escalation_seconds:
            alert.tier += 1
            alert.last_escalated_at = now
            _notify(db, alert, alert.tier)
            moved += 1
    return moved


def sweep_missed_doses(db: Session, now: dt.datetime) -> int:
    """Record and alert on doses whose window has closed with no med_taken event.

    Checks today and yesterday (patient-local) so a window that closes just
    after midnight is not skipped. A schedule created after its window had
    already closed is ignored.
    """
    created = 0
    schedules = db.scalars(
        select(MedicationSchedule).where(MedicationSchedule.active.is_(True))
    ).all()
    for sched in schedules:
        patient = db.get(Patient, sched.patient_id)
        for day_offset in (0, -1):
            due_utc, end_utc, due_local = dose_window(sched, patient, now, day_offset)
            if now <= end_utc or sched.created_at > due_utc:
                continue
            if dose_outcome(db, sched, due_utc, end_utc):
                continue
            event = Event(
                patient_id=patient.id,
                schedule_id=sched.id,
                type="med_missed",
                payload={"name": sched.name, "due": due_local.strftime("%H:%M")},
                occurred_at=end_utc,
            )
            db.add(event)
            db.flush()
            raise_alert(
                db, event, "warning", f"Missed dose: {sched.name} at {due_local.strftime('%H:%M')}", now
            )
            created += 1
    return created
