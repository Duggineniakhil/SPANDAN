"""Bearing geometry table and fault-frequency calculator (M2-20).

Fault frequencies as multiples of shaft speed (standard kinematic formulas, stationary outer race):
  BPFO = n/2 · (1 − d/D·cosφ)          outer-race defect
  BPFI = n/2 · (1 + d/D·cosφ)          inner-race defect
  BSF  = D/(2d) · (1 − (d/D·cosφ)²)    ball spin; a ball defect hits both races, so 2×BSF is often the strongest
  FTF  = 1/2 · (1 − d/D·cosφ)          cage
"""
import csv
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).with_name("bearings.csv")


@dataclass(frozen=True)
class Bearing:
    model: str
    n_elements: int
    ball_diameter_mm: float
    pitch_diameter_mm: float
    contact_angle_deg: float
    source: str

    @property
    def approximate(self) -> bool:
        return self.source.startswith("approximate")


@dataclass(frozen=True)
class FaultOrders:
    """Fault frequencies as multiples of shaft speed."""
    bpfo: float
    bpfi: float
    bsf: float
    ftf: float

    def hz(self, shaft_hz: float) -> dict[str, float]:
        return {k: v * shaft_hz for k, v in self.__dict__.items()}


@lru_cache
def table() -> dict[str, Bearing]:
    with TABLE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["model"]: Bearing(r["model"], int(r["n_elements"]), float(r["ball_diameter_mm"]),
                                float(r["pitch_diameter_mm"]), float(r["contact_angle_deg"]), r["source"])
            for r in rows}


def normalise_model(model: str) -> str:
    """'SKF 6205-2RS C3' -> '6205', 'UCP204' -> 'UC204', 'za2115' -> 'ZA-2115'."""
    m = model.upper().strip()
    m = re.sub(r"^(SKF|FAG|NBC|NSK|NTN|KOYO|TIMKEN|ZKL)\s+", "", m)
    m = re.sub(r"[-\s]?(2RS1?|2RSH|2Z|ZZ|RS|Z|JEM)\b.*$", "", m)
    m = re.sub(r"\s+C[0-5]$", "", m).strip()
    if re.fullmatch(r"UCP?\s*-?(\d{3})", m):
        m = "UC" + re.fullmatch(r"UCP?\s*-?(\d{3})", m).group(1)
    if re.fullmatch(r"ZA-?2115", m):
        m = "ZA-2115"
    return m


def lookup(model: str | None) -> Bearing | None:
    return table().get(normalise_model(model)) if model else None


def fault_orders(b: Bearing) -> FaultOrders:
    r = b.ball_diameter_mm / b.pitch_diameter_mm * math.cos(math.radians(b.contact_angle_deg))
    n = b.n_elements
    return FaultOrders(
        bpfo=n / 2 * (1 - r),
        bpfi=n / 2 * (1 + r),
        bsf=b.pitch_diameter_mm / (2 * b.ball_diameter_mm) * (1 - r * r),
        ftf=0.5 * (1 - r),
    )
