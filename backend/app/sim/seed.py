"""Sandbox directory of dealers, parts, mechanics and mechanic calendars around Mysuru.

All names are fictional. `reset()` wipes and recreates the sandbox; slots are generated
relative to "now" so the demo always has upcoming free slots.
"""
import random
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models import Dealer, Job, Mechanic, MechanicSlot, Message, Part, Quote

IST = timezone(timedelta(hours=5, minutes=30))
SITE = (12.2958, 76.6394)  # default mill location (Mysuru) when the owner has none

DEALERS = [
    # name, phone, lat, lng, reply style, [(part_code, description, price, in_stock, lead_days)]
    ("Sri Lakshmi Bearings", "+910000000101", 12.3051, 76.6551, "kn_en", [
        ("6205-2RS", "SKF 6205-2RS deep groove ball bearing", 1450, True, 0),
        ("6204-2RS", "SKF 6204-2RS deep groove ball bearing", 1150, True, 0),
        ("UCP204", "NBC UCP204 pillow block bearing", 980, True, 0),
    ]),
    ("Kaveri Spares", "+910000000102", 12.3375, 76.6200, "hi_en", [
        ("6205-2RS", "NBC 6205-2RS deep groove ball bearing", 1180, True, 0),
        ("B-42", "Fenner B-42 V-belt", 420, True, 0),
    ]),
    ("Mysore Machinery Stores", "+910000000103", 12.2724, 76.6698, "en_formal", [
        ("6205-2RS", "FAG 6205-2RS deep groove ball bearing", 1620, False, 2),
        ("6204-2RS", "FAG 6204-2RS deep groove ball bearing", 1300, False, 2),
    ]),
    ("Chamundi Engineering Traders", "+910000000104", 12.2860, 76.6100, "injection", [
        ("6205-2RS", "ZKL 6205-2RS deep groove ball bearing", 1300, True, 0),
    ]),
    ("Ganesh Motor Works", "+910000000105", 12.3200, 76.6450, "kn_en", [
        ("L-100", "L-100 jaw coupling with spider", 650, True, 0),
        ("B-42", "B-42 V-belt (local)", 390, True, 0),
    ]),
    ("Balaji Bearing House", "+910000000106", 12.3480, 76.6800, "hi_en", [
        ("6205-2RS", "SKF 6205-2RS deep groove ball bearing", 1490, True, 0),
        ("6204-2RS", "NBC 6204-2RS deep groove ball bearing", 890, True, 0),
    ]),
]

MECHANICS = [
    # name, phone, skills, rate, lat, lng
    ("Ravi Kumar", "+910000000201", ["bearing", "motor", "alignment", "balancing"], 500, 12.3100, 76.6500),
    ("Suresh", "+910000000202", ["bearing", "alignment", "balancing"], 450, 12.2900, 76.6300),
    ("Mahesh", "+910000000203", ["motor", "electrical"], 600, 12.3300, 76.6700),
    ("Anand", "+910000000204", ["general", "belt", "bearing", "tightening"], 400, 12.2800, 76.6600),
]

SLOT_HOURS = (9, 11, 14, 16)  # 2-hour slots, IST
DAYS_AHEAD = 7


def reset(db: Session, now: datetime | None = None, seed: int = 11) -> dict[str, int]:
    now = now or datetime.now(UTC)
    rnd = random.Random(seed)

    # Jobs reference slots; quotes reference dealers. Plans keep their own copy of details.
    db.execute(delete(Job))
    db.execute(delete(Message).where(Message.to_kind.in_(("dealer", "mechanic"))))  # sandbox inboxes
    db.execute(delete(Quote))
    db.execute(update(MechanicSlot).values(held_for_event_id=None))
    db.execute(delete(MechanicSlot))
    db.execute(delete(Mechanic))
    db.execute(delete(Part))
    db.execute(delete(Dealer))

    parts = 0
    for name, phone, lat, lng, style, items in DEALERS:
        dealer = Dealer(id=uuid.uuid4(), name=name, phone=phone, lat=lat, lng=lng, sandbox=True, reply_style=style)
        db.add(dealer)
        for code, desc, price, stock, lead in items:
            db.add(Part(id=uuid.uuid4(), dealer_id=dealer.id, part_code=code, description=desc,
                        price_inr=price, in_stock=stock, lead_time_days=lead))
            parts += 1

    slots = 0
    today = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    for name, phone, skills, rate, lat, lng in MECHANICS:
        mech = Mechanic(id=uuid.uuid4(), name=name, phone=phone, skills=skills, rate_inr=rate, lat=lat, lng=lng, sandbox=True)
        db.add(mech)
        for d in range(DAYS_AHEAD + 1):
            for h in SLOT_HOURS:
                start = today + timedelta(days=d, hours=h)
                if start <= now:
                    continue
                busy = rnd.random() < 0.4
                db.add(MechanicSlot(id=uuid.uuid4(), mechanic_id=mech.id, start_at=start,
                                    end_at=start + timedelta(hours=2), status="booked" if busy else "free"))
                slots += 1
    db.flush()
    return {"dealers": len(DEALERS), "parts": parts, "mechanics": len(MECHANICS), "slots": slots}
