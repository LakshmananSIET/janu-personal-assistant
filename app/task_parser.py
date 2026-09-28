from __future__ import annotations

from datetime import datetime, timedelta
import re


def parse_task(text: str) -> dict | None:
    """Offline fallback parser used when the free trial has no paid AI API."""
    lower = text.lower().strip()

    # Reminder requests must also work without the AI API.
    reminder_match = re.search(
        r"remind\s+me\s+(?:to\s+)?(.+?)(?=\s+(?:at|on|tomorrow|today|before|by)\b|$)",
        lower,
    )

    task_match = re.search(
        r"(?:need to|have to|must|should|finish|complete|do)\s+(.+?)(?=\s+(?:before|by|at|tomorrow|today|on)\b|$)",
        lower,
    )

    has_task_signal = (
        reminder_match is not None
        or any(
            phrase in lower
            for phrase in ("need to", "have to", "must", "should", "finish", "complete")
        )
    )
    if not has_task_signal:
        return None

    if reminder_match:
        task = reminder_match.group(1).strip()
    elif task_match:
        task = task_match.group(1).strip()
    else:
        task = text.strip()

    # Handle wording such as "For ticket booking remind me at 4:30 PM".
    if "remind me" in lower and task.lower().startswith("at "):
        prefix = re.split(r"\bremind\s+me\b", lower, maxsplit=1)[0].strip(" ,")
        if prefix:
            task = prefix

    task = re.sub(r"\s+", " ", task).strip(" .,")

    now = datetime.now()
    due_date = None

    if "tomorrow" in lower:
        due_date = (now + timedelta(days=1)).date().isoformat()
    elif "today" in lower:
        due_date = now.date().isoformat()

    # A reminder time is different from a task deadline.
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

        # "remind me at" means an actual reminder time. If no date is given,
        # treat it as today's time; if that time has already passed, schedule
        # it for tomorrow rather than silently losing the reminder.
        if re.search(r"\bremind\s+me\b", lower):
            reminder_date = (
                datetime.fromisoformat(due_date).date()
                if due_date
                else now.date()
            )
            reminder_dt = datetime.combine(
                reminder_date, datetime.min.time()
            ).replace(hour=hour, minute=minute)

            if not due_date and reminder_dt <= now:
                reminder_dt += timedelta(days=1)

            reminder_at = reminder_dt.astimezone().isoformat(timespec="seconds")
            due_date = reminder_dt.date().isoformat()

    return {
        "task": task,
        "due_date": due_date,
        "deadline": deadline,
        "reminder_at": reminder_at,
        "status": "pending",
        "source_text": text,
    }
