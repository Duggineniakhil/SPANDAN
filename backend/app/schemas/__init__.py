"""Request/response schemas (contract C2, doc 07 §1)."""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["kn", "hi", "en"]
HHMM = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# ---------- Owners ----------

class IdleWindow(StrictModel):
    dow: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _start_before_end(self) -> "IdleWindow":
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class OwnerCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=r"^\+?[0-9]{10,13}$")
    language: Language
    spending_limit_inr: int = Field(default=2000, ge=0, le=500_000)
    idle_windows: list[IdleWindow] = Field(default_factory=list, max_length=21)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    phone: str
    language: Language
    spending_limit_inr: int
    idle_windows: list[IdleWindow]
    lat: float | None
    lng: float | None
    created_at: datetime


# ---------- Machines ----------

class MachineCreate(StrictModel):
    owner_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    machine_type: str = Field(default="flour_mill_motor", max_length=60)
    motor_rpm: int | None = Field(default=None, gt=0, le=20_000)
    bearing_model: str | None = Field(default=None, max_length=40)
    sensor_id: str | None = Field(default=None, max_length=64)


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    machine_type: str
    motor_rpm: int | None
    bearing_model: str | None
    sensor_id: str | None
    state: str
    anomaly_threshold: float | None
    threshold_base: float | None = None  # from the last baseline; false alarms raise anomaly_threshold above it
    model_version: str | None
    baseline_started_at: datetime | None
    baseline_done_at: datetime | None
    created_at: datetime


class BaselineComplete(StrictModel):
    anomaly_threshold: float = Field(gt=0)
    model_version: str = Field(min_length=1, max_length=60)


# ---------- Telemetry ----------

class TelemetryRow(StrictModel):
    row_id: uuid.UUID
    ts: AwareDatetime
    features: dict[str, float] = Field(min_length=1, max_length=100)
    anomaly_score: float | None = Field(default=None, ge=0)
    health_index: float | None = Field(default=None, ge=0, le=100)
    rpm_estimate: float | None = Field(default=None, ge=0)
    model_version: str | None = Field(default=None, max_length=60)

    @field_validator("features")
    @classmethod
    def _feature_names(cls, v: dict[str, float]) -> dict[str, float]:
        for name in v:
            if not name or len(name) > 40:
                raise ValueError(f"invalid feature name: {name!r}")
        return v


class TelemetryBatch(StrictModel):
    device_id: str = Field(min_length=1, max_length=64)
    machine_id: uuid.UUID
    rows: list[TelemetryRow] = Field(min_length=1, max_length=1000)


class RejectedRow(BaseModel):
    row_id: uuid.UUID
    reason: str


class TelemetryBatchResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[RejectedRow]


# ---------- Anomaly events ----------

class AnomalyEventIn(StrictModel):
    machine_id: uuid.UUID
    started_at: AwareDatetime
    peak_score: float | None = Field(default=None, ge=0)


class DiagnosisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    faults: list[dict]
    rul_days_low: float | None
    rul_days_high: float | None
    rul_status: str
    model_versions: dict
    created_at: datetime


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    owner_id: uuid.UUID
    plan: dict
    total_cost_inr: int
    state: str
    voice_script: dict | None
    created_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    decided_via: str | None = None
    reminded_at: datetime | None = None


class AnomalyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    machine_id: uuid.UUID
    started_at: datetime
    peak_score: float | None
    status: str
    source: str
    created_at: datetime


# ---------- Feedback (M2-32, M2-33) ----------

ActualFault = Literal["bearing_outer", "bearing_inner", "bearing_ball", "imbalance", "misalignment", "looseness",
                      "no_fault_found", "other"]


class JobOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    status: str
    mechanic: str
    start: datetime
    end: datetime
    job_card: dict | None = None


class AnomalyEventDetail(AnomalyEventOut):
    diagnosis: DiagnosisOut | None = None
    plans: list[PlanOut] = []
    jobs: list[JobOut] = []


class JobCardIn(StrictModel):
    actual_fault: ActualFault = Field(description="What the mechanic actually found")
    parts_replaced: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default=[], max_length=10)
    notes: str = Field(default="", max_length=1000)
    from_phone: str = Field(min_length=10, max_length=20,
                            description="The booked mechanic's or the owner's number (the form runs on the owner's phone)")


class JobCardOut(BaseModel):
    job: JobOut
    event_status: str
    machine_state: str  # "baseline": the phone must learn a new baseline now
    diagnosis_correct: bool | None


class FalseAlarmIn(StrictModel):
    from_phone: str = Field(min_length=10, max_length=20, description="Owner's registered number")
    note: str = Field(default="", max_length=300)


class FalseAlarmOut(BaseModel):
    event: AnomalyEventOut
    machine_state: str
    anomaly_threshold: float | None
    threshold_base: float | None
    threshold_raise_pct: float  # vs the baseline's threshold; the phone applies the same value
    cancelled_plan_id: uuid.UUID | None = None


class PlannerResultOut(BaseModel):
    status: Literal["planned", "failed", "skipped"]
    plan_id: uuid.UUID | None = None
    provider: str | None = None
    reason: str | None = None
    tool_calls: int = 0


# ---------- Approval ----------

class DecisionIn(StrictModel):
    decision: Literal["approve", "reject"]
    channel: Literal["tap", "voice", "sms"]
    from_phone: str = Field(min_length=10, max_length=20, description="Number the reply came from")
    transcript: str | None = Field(default=None, max_length=2000, description="Voice reply transcript, if any")


class DecisionOut(BaseModel):
    plan: PlanOut
    executed: bool | None = None  # None for a rejection
    reason: str | None = None
    job_id: uuid.UUID | None = None
    replanning: bool = False


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    to_kind: str
    to_id: uuid.UUID
    plan_id: uuid.UUID | None
    event_id: uuid.UUID | None
    kind: str
    lang: str
    text: str
    channel: str
    created_at: datetime
    read_at: datetime | None


class SweepOut(BaseModel):
    reminded: int
    expired: int


# ---------- Dashboard reads ----------

class TelemetryPoint(BaseModel):
    ts: datetime
    anomaly_score: float | None
    health_index: float | None
    rpm_estimate: float | None
    features: dict[str, float | None] = {}


class TelemetrySeries(BaseModel):
    machine_id: uuid.UUID
    from_ts: datetime
    to_ts: datetime
    total_rows: int
    downsampled: bool  # True: each point is a time bucket (max score, min health, mean rpm/features)
    bucket_seconds: float | None = None
    points: list[TelemetryPoint]


class LastReading(BaseModel):
    ts: datetime
    anomaly_score: float | None
    health_index: float | None
    received_at: datetime


class HealthOut(BaseModel):
    machine_id: uuid.UUID
    state: str
    anomaly_threshold: float | None
    last_reading: LastReading | None
    minutes_since_last_reading: float | None
    readings_24h: int
    open_event: AnomalyEventOut | None
    pending_plan_id: uuid.UUID | None


class LatestDiagnosisOut(DiagnosisOut):
    event_id: uuid.UUID


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor: str
    action: str
    entity: str
    entity_id: uuid.UUID | None
    details: dict


# ---------- Raw windows (for diagnosis) ----------

class RawWindowsIn(StrictModel):
    kind: Literal["baseline", "alert"]
    ts: AwareDatetime
    fs: int = Field(ge=1000, le=51200, description="Sampling rate, Hz")
    rpm: float | None = Field(default=None, ge=60, le=30000)
    windows: list[Annotated[list[float], Field(min_length=1024, max_length=65536)]] = Field(min_length=1, max_length=3)

    @field_validator("windows")
    @classmethod
    def _range(cls, v: list[list[float]]) -> list[list[float]]:
        for w in v:
            if max(abs(min(w)), abs(max(w))) > 16:
                raise ValueError("samples must be in g within ±16 g")
        return v


class RawWindowsOut(BaseModel):
    stored: int
    rediagnosed: bool = False  # an unclear alert now has a clear fault (and gets planned)


class SpokenOut(BaseModel):
    """What the app says back: text in the owner's language, plus cached audio if there is any."""
    lang: str
    text: str
    audio_url: str | None = None


class VoiceReplyOut(BaseModel):
    transcript: str
    intent: Literal["approve", "reject", "question", "unclear"]
    intent_source: str  # keywords | llm | empty
    action: Literal["approved", "rejected", "replanning", "reask", "use_buttons"]
    attempt: int
    question: str | None = None
    decision: DecisionOut | None = None  # for approve/reject
    say: SpokenOut
