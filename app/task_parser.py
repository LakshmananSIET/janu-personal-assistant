from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


def parse_task(text: str) -> dict | None:
    """Offline fallback parser used when the free trial has no paid AI API."""
    lower = text.lower().strip()

    reminder_phrase = re.search(r"\bremind\s+me\b", lower)
    reminder_match = re.search(
        r"\bremind\s+me\s+(?:to\s+)?(.+?)(?=\s+(?:at|on|tomorrow|today|before|by)\b|$)",
        lower,
    )

    task_match = re.search(
        r"(?:need to|have to|must|should|finish|complete|do)\s+(.+?)(?=\s+(?:before|by|at|tomorrow|today|on)\b|$)",
        lower,
    )

    has_task_signal = (
        reminder_phrase is not None
        or any(
            phrase in lower
            for phrase in ("need to", "have to", "must", "should", "finish", "complete")
        )
    )
    if not has_task_signal:
        return None

    if reminder_phrase and not (reminder_match and reminder_match.group(1).strip()):
        # Example: "For ticket booking remind me at 4:30 PM"
        prefix = lower.split("remind me", 1)[0].strip(" ,")
        task = prefix or text.strip()
    elif reminder_match:
        task = reminder_match.group(1).strip()
    elif task_match:
        task = task_match.group(1).strip()
    else:
        task = text.strip()

    task = re.sub(r"\s+", " ", task).strip(" .,")

    now = datetime.now(IST)
    due_date = None

    if "tomorrow" in lower:
        due_date = (now + timedelta(days=1)).date().isoformat()
    elif "today" in lower:
        due_date = now.date().isoformat()

    time_match = re.search(
        r"\b(?:at|before|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        lower,
    )

    deadline = None
    reminder_at = None
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        time_text = f"{hour:02d}:{minute:02d}"

        if re.search(r"\b(?:before|by)\b", lower):
            deadline = time_text

        if reminder_phrase:
            reminder_date = (
                datetime.fromisoformat(due_date).date()
                if due_date
                else now.date()
            )
            reminder_dt = datetime.combine(
                reminder_date, datetime.min.time(), tzinfo=IST
            ).replace(hour=hour, minute=minute)

            if not due_date and reminder_dt <= now:
                reminder_dt += timedelta(days=1)

            reminder_at = reminder_dt.isoformat(timespec="seconds")
            due_date = reminder_dt.date().isoformat()

    return {
        "task": task,
        "due_date": due_date,
        "deadline": deadline,
        "reminder_at": reminder_at,
        "status": "pending",
        "source_text": text,
    }
