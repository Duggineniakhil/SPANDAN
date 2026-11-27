"""Owner messages in kn / hi / en, plus sandbox messages to dealers and mechanics.

Fixed templates, not LLM text, so they are predictable and safe. The plan itself is explained by the
agent's voice script. The Kannada and Hindi wording still needs a native speaker's review before the demo.
Numbers, dates and times are always digits.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnomalyEvent, Machine, Message, Owner, Plan

IST = timezone(timedelta(hours=5, minutes=30))

OWNER_TEMPLATES: dict[str, dict[str, str]] = {
    "reminder": {
        "kn": "ನೆನಪಿಸುವಿಕೆ: {machine} ದುರಸ್ತಿ ಯೋಜನೆ ನಿಮ್ಮ ಉತ್ತರಕ್ಕಾಗಿ ಕಾಯುತ್ತಿದೆ. ಒಟ್ಟು ₹{total}, {when}. "
              "ಹೌದು ಅಥವಾ ಬೇಡ ಎಂದು ಉತ್ತರಿಸಿ.",
        "hi": "याद दिलाना: {machine} की मरम्मत योजना आपके जवाब का इंतज़ार कर रही है। कुल ₹{total}, {when}। "
              "हाँ या नहीं में जवाब दें।",
        "en": "Reminder: the repair plan for {machine} is waiting for your answer. Total ₹{total}, {when}. "
              "Please reply yes or no.",
    },
    "expired": {
        "kn": "48 ಗಂಟೆಗಳಲ್ಲಿ ಉತ್ತರ ಬರದ ಕಾರಣ {machine} ದುರಸ್ತಿ ಯೋಜನೆಯನ್ನು ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ. ಏನನ್ನೂ ಬುಕ್ ಮಾಡಿಲ್ಲ. "
              "ಹೊಸ ಯೋಜನೆಗಾಗಿ ಯಾವಾಗ ಬೇಕಾದರೂ ಕೇಳಿ.",
        "hi": "48 घंटे में जवाब नहीं आया, इसलिए {machine} की मरम्मत योजना रद्द कर दी गई। कुछ भी बुक नहीं किया गया। "
              "नई योजना कभी भी माँग सकते हैं।",
        "en": "No reply in 48 hours, so the repair plan for {machine} was cancelled. Nothing was booked. "
              "You can ask for a new plan any time.",
    },
    "booking_confirmed": {
        "kn": "ಬುಕ್ ಆಗಿದೆ: {mechanic} {when} ಕ್ಕೆ ಬರುತ್ತಾರೆ.{part_line} ಒಟ್ಟು ₹{total}.",
        "hi": "बुक हो गया: {mechanic} {when} को आएँगे।{part_line} कुल ₹{total}।",
        "en": "Booked: {mechanic} will come on {when}.{part_line} Total ₹{total}.",
    },
    "part_line": {
        "kn": " {part} ಭಾಗವನ್ನು {dealer} ಅಂಗಡಿಯಲ್ಲಿ ತೆಗೆದುಕೊಳ್ಳುವಾಗ ₹{part_cost} ಪಾವತಿಸಿ.",
        "hi": " {part} {dealer} से लेते समय ₹{part_cost} दें।",
        "en": " Pick up {part} from {dealer} and pay ₹{part_cost} there.",
    },
    "rejected": {
        "kn": "ಸರಿ, {machine} ದುರಸ್ತಿ ಯೋಜನೆಯನ್ನು ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ. ಏನನ್ನೂ ಬುಕ್ ಮಾಡಿಲ್ಲ.",
        "hi": "ठीक है, {machine} की मरम्मत योजना रद्द कर दी गई। कुछ भी बुक नहीं किया गया।",
        "en": "Okay, the repair plan for {machine} was cancelled. Nothing was booked.",
    },
    "slot_lost": {
        "kn": "ಮೆಕ್ಯಾನಿಕ್ ಸಮಯ ಈಗ ಲಭ್ಯವಿಲ್ಲ, ಆದ್ದರಿಂದ ಏನನ್ನೂ ಬುಕ್ ಮಾಡಿಲ್ಲ. {machine} ಗಾಗಿ ಹೊಸ ಯೋಜನೆ ತಯಾರಿಸುತ್ತಿದ್ದೇವೆ.",
        "hi": "मैकेनिक का समय अब उपलब्ध नहीं है, इसलिए कुछ भी बुक नहीं किया गया। {machine} के लिए नई योजना बना रहे हैं।",
        "en": "The mechanic's slot is no longer available, so nothing was booked. We are preparing a new plan "
              "for {machine}.",
    },
    "could_not_plan": {
        "kn": "{machine} ನಲ್ಲಿ ಅಸಾಮಾನ್ಯ ಕಂಪನ ಕಂಡುಬಂದಿದೆ. ದುರಸ್ತಿ ಯೋಜನೆಯನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ತಯಾರಿಸಲು ಆಗಲಿಲ್ಲ. "
              "ದಯವಿಟ್ಟು ಮೆಕ್ಯಾನಿಕ್‌ಗೆ ಕರೆ ಮಾಡಿ.",
        "hi": "{machine} में असामान्य कंपन दिखा है। मरम्मत योजना अपने-आप नहीं बन सकी। कृपया मैकेनिक को बुलाएँ।",
        "en": "{machine} is vibrating unusually. We could not prepare a repair plan automatically. "
              "Please call a mechanic.",
    },
    "inspection": {
        "kn": "{machine} ನಲ್ಲಿ ಅಸಾಮಾನ್ಯ ಕಂಪನ ಕಂಡುಬಂದಿದೆ, ಆದರೆ ಕಾರಣ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಮೆಕ್ಯಾನಿಕ್‌ನಿಂದ ಪರಿಶೀಲಿಸಿ.",
        "hi": "{machine} में असामान्य कंपन दिखा है, पर कारण साफ़ नहीं है। कृपया मैकेनिक से जाँच करवाएँ।",
        "en": "{machine} is vibrating unusually, but the cause is not clear. Please get it inspected by a mechanic.",
    },
}

# Sandbox messages to simulated dealers and mechanics (English)
DEALER_ORDER = ("Order confirmation (sandbox): {qty} x {part_code} for {owner}. Pickup by the owner, "
                "who pays ₹{price} at pickup. Ref {ref}.")
MECHANIC_BOOKING = ("Booking confirmed (sandbox): {when} to {end} at {owner}'s mill ({machine}). "
                    "Rate ₹{rate}. Likely fault: {fault}. Ref {ref}.")


def fmt_when(iso: str | datetime) -> str:
    dt = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
    return dt.astimezone(IST).strftime("%d/%m %H:%M")


def send(db: Session, *, to_kind: str, to_id: uuid.UUID, kind: str, lang: str, text: str,
         plan_id: uuid.UUID | None = None, event_id: uuid.UUID | None = None) -> Message:
    msg = Message(id=uuid.uuid4(), to_kind=to_kind, to_id=to_id, kind=kind, lang=lang, text=text,
                  plan_id=plan_id, event_id=event_id)
    db.add(msg)
    return msg


def owner_text(kind: str, lang: str, **values) -> str:
    templates = OWNER_TEMPLATES[kind]
    return templates.get(lang, templates["en"]).format(**values)


def notify_owner(db: Session, owner: Owner, kind: str, *, plan: Plan | None = None,
                 event_id: uuid.UUID | None = None, once: bool = False, **values) -> Message | None:
    """Send a template message to the owner. `once`: skip if this kind was already sent for the event."""
    event_id = event_id or (plan.event_id if plan else None)
    if once and event_id and db.scalar(select(Message.id).where(
            Message.to_kind == "owner", Message.event_id == event_id, Message.kind == kind)):
        return None
    if "machine" not in values and event_id:
        event = db.get(AnomalyEvent, event_id)
        values["machine"] = db.get(Machine, event.machine_id).name
    return send(db, to_kind="owner", to_id=owner.id, kind=kind, lang=owner.language,
                text=owner_text(kind, owner.language, **values), plan_id=plan.id if plan else None,
                event_id=event_id)


def plan_values(plan: Plan) -> dict:
    """Values for the templates, taken from the plan's own (server-built) actions."""
    acts = {a["type"]: a for a in plan.plan.get("actions", [])}
    mech = acts.get("book_mechanic", {})
    return {"total": plan.total_cost_inr, "when": fmt_when(mech["start"]) if mech else "-",
            "mechanic": mech.get("mechanic", "-")}
