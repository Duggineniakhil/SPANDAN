"""All database tables (doc 07 §2).

Location is stored as lat/lng floats instead of PostGIS GEOGRAPHY to keep the
prototype free of the PostGIS extension.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

LANGUAGES = ("kn", "hi", "en")
MACHINE_STATES = ("setup", "baseline", "monitoring", "alert", "maintenance")
EVENT_STATUSES = ("open", "diagnosed", "planned", "resolved", "false_alarm")
PLAN_STATES = ("draft", "pending", "approved", "rejected", "expired", "executed", "cancelled")
SLOT_STATUSES = ("free", "held", "booked")
JOB_STATUSES = ("scheduled", "done", "no_show")
AUDIT_ACTORS = ("system", "agent", "owner", "mechanic", "operator", "device")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"
    __table_args__ = (CheckConstraint(_in("language", LANGUAGES), name="language_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    language: Mapped[str] = mapped_column(String(2))
    spending_limit_inr: Mapped[int] = mapped_column(Integer, default=2000)
    idle_windows: Mapped[list] = mapped_column(JSONB, default=list)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _created_at()


class Machine(Base):
    __tablename__ = "machines"
    __table_args__ = (CheckConstraint(_in("state", MACHINE_STATES), name="state_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    machine_type: Mapped[str] = mapped_column(String(60))
    motor_rpm: Mapped[int | None] = mapped_column(Integer)
    bearing_model: Mapped[str | None] = mapped_column(String(40))
    # Sensor MAC, or a replay source ID while running on datasets
    sensor_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="setup")
    anomaly_threshold: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(60))
    baseline_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Telemetry(Base):
    __tablename__ = "telemetry"
    __table_args__ = (Index("ix_telemetry_machine_ts", "machine_id", "ts"),)

    row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"))
    device_id: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    features: Mapped[dict] = mapped_column(JSONB)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    health_index: Mapped[float | None] = mapped_column(Float)
    rpm_estimate: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(60))
    received_at: Mapped[datetime] = _created_at()


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    __table_args__ = (CheckConstraint(_in("status", EVENT_STATUSES), name="status_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    peak_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="open")
    source: Mapped[str] = mapped_column(String(10))  # phone | server
    created_at: Mapped[datetime] = _created_at()


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("anomaly_events.id"), index=True)
    faults: Mapped[list] = mapped_column(JSONB)
    rul_days_low: Mapped[float | None] = mapped_column(Float)
    rul_days_high: Mapped[float | None] = mapped_column(Float)
    rul_status: Mapped[str] = mapped_column(String(30))
    model_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()


class Dealer(Base):
    __tablename__ = "dealers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    # Sandbox: how this simulated dealer writes replies (see app/sim)
    reply_style: Mapped[str] = mapped_column(String(20), default="kn_en")
    phone: Mapped[str] = mapped_column(String(20))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    sandbox: Mapped[bool] = mapped_column(Boolean, default=True)


class Part(Base):
    __tablename__ = "parts_catalog"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dealer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dealers.id"), index=True)
    part_code: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    price_inr: Mapped[int] = mapped_column(Integer)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)


class Mechanic(Base):
    __tablename__ = "mechanics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    skills: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    rate_inr: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    sandbox: Mapped[bool] = mapped_column(Boolean, default=True)


class MechanicSlot(Base):
    __tablename__ = "mechanic_slots"
    __table_args__ = (
        CheckConstraint(_in("status", SLOT_STATUSES), name="status_valid"),
        CheckConstraint("end_at > start_at", name="end_after_start"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    mechanic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mechanics.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="free")
    # While a plan waits for the owner, its slot is held for that anomaly event
    held_for_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("anomaly_events.id"))
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


QUOTE_STATUSES = ("received", "unavailable")


class Quote(Base):
    """A dealer's answer to a quote request. The price stored here is the source of truth;
    the agent only refers to quotes by id and can't change the price."""

    __tablename__ = "quotes"
    __table_args__ = (CheckConstraint(_in("status", QUOTE_STATUSES), name="status_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("anomaly_events.id"), index=True)
    dealer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dealers.id"))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts_catalog.id"))
    part_code: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_inr: Mapped[int | None] = mapped_column(Integer)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))
    dealer_reply: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (CheckConstraint(_in("state", PLAN_STATES), name="state_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("anomaly_events.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    plan: Mapped[dict] = mapped_column(JSONB)
    total_cost_inr: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(12), default="draft")
    voice_script: Mapped[dict | None] = mapped_column(JSONB)
    voice_audio_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_via: Mapped[str | None] = mapped_column(String(10))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), index=True)
    mechanic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mechanics.id"))
    slot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mechanic_slots.id"))
    status: Mapped[str] = mapped_column(String(10), default="scheduled")
    job_card: Mapped[dict | None] = mapped_column(JSONB)


class FeedbackLabel(Base):
    __tablename__ = "feedback_labels"

    id: Mapped[uuid.UUID] = _uuid_pk()
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("anomaly_events.id"))
    label: Mapped[str] = mapped_column(String(40))  # fault name | false_alarm
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created_at()


class AuditLog(Base):
    """Append-only. A database trigger (see migration) blocks UPDATE and DELETE."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(_in("actor", AUDIT_ACTORS), name="actor_valid"),
        Index("ix_audit_entity", "entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = _created_at()
    actor: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
