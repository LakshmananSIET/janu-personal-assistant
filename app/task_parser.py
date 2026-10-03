from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


# Natural Tanglish reminder/task phrases.
REMINDER_PATTERNS = [
    r"\bremind\s+me\b",
    r"\breminder\b",
    r"\bremind\s+pannu\b",
    r"\bremind\s+pan\b",
    r"\bnyabagam\s+(?:paduthu|paduthunga|vachuko|vachukko|vainga|vechuko)\b",
]

TASK_PATTERNS = [
    r"\btask\b",
    r"\btask\s+(?:add|podu|pannu|set)\b",
    r"\btask[- ]?a\s+(?:add|podu|pannu|set)\b",
]


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _is_negated(text: str) -> bool:
    """Ignore common English/Tanglish negative reminder requests."""
    return bool(
        re.search(
            r"\b(?:no|not|don't|dont|do not|never|vendam|venam|venda|panna vendam|remind panna vendam)\b",
            text,
        )
    )


def _extract_time(text: str):
    # English + common Tanglish time markers.
    return re.search(
        r"\b(?:at|before|by|ku|kku|mani|manikku|time)\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        text,
    )


def _clean_task(task: str) -> str:
    task = re.sub(
        r"\b(?:tomorrow|today|naalaikku|naalai|innaikku|indru)\b",
        "",
        task,
        flags=re.I,
    )
    task = re.sub(
        r"\s+(?:at|before|by|ku|kku|manikku|mani|time)\s+"
        r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b.*$",
        "",
        task,
        flags=re.I,
    )
    task = re.sub(r"\s+", " ", task).strip(" .,:-")
    task = re.sub(
        r"^(?:to|please|kindly|oru|oru\s+task\s*[:\-]?)\s+",
        "",
        task,
        flags=re.I,
    )
    return task


def parse_task(text: str) -> dict | None:
    """Parse simple English/Tanglish tasks and reminders without an API key."""
    original = text.strip()
    lower = original.lower()

    reminder_intent = _has_any(lower, REMINDER_PATTERNS)
    task_intent = _has_any(lower, TASK_PATTERNS) and not reminder_intent

    if not reminder_intent and not task_intent:
        return None

    # Negative requests must not create reminders/tasks.
    if reminder_intent and _is_negated(lower):
        return None

    # Extract task text.
    if reminder_intent:
        marker = None
        for pattern in REMINDER_PATTERNS:
            match = re.search(pattern, lower)
            if match:
                marker = match
                break

        suffix = lower[marker.end():].strip(" ,") if marker else lower
        # "remind pannu production report" / "remind pannu to check..."
        suffix = re.sub(r"^(?:me|to|about|for)\s+", "", suffix).strip()

        time_match = _extract_time(suffix)
        if time_match:
            before_time = suffix[:time_match.start()].strip(" ,")
            after_time = suffix[time_match.end():].strip(" ,")

            # Supports:
            # "remind pannu production report at 6 PM"
            # "remind pannu at 6 PM production report"
            task = before_time or after_time
        else:
            task = suffix

        if not task:
            task = original

    else:
        task_match = re.search(r"\btask\b\s*[:\-]?\s*(.*)$", lower)
        task = task_match.group(1).strip() if task_match else original

        task = re.sub(
            r"^(?:add|create|make|take|podu|pannu|set)\s+(?:a\s+)?task\s*[:\-]?\s*",
            "",
            task,
            flags=re.I,
        )
        # "task-a add pannu: Pickering testing"
        task = re.sub(
            r"^[-: ]*(?:add|podu|pannu|set)\s+(?:task[- ]?a\s*)?",
            "",
            task,
            flags=re.I,
        )

    task = _clean_task(task)

    if not task:
        return None

    now = datetime.now(IST)
    due_date = None

    if re.search(r"\b(?:tomorrow|naalaikku|naalai)\b", lower):
        due_date = (now + timedelta(days=1)).date().isoformat()
    elif re.search(r"\b(?:today|innaikku|indru)\b", lower):
        due_date = now.date().isoformat()

    time_match = _extract_time(lower)
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

        if reminder_intent:
            reminder_date = (
                datetime.fromisoformat(due_date).date()
                if due_date
                else now.date()
            )

            reminder_dt = datetime.combine(
                reminder_date,
                datetime.min.time(),
                tzinfo=IST,
            ).replace(hour=hour, minute=minute)

            if not due_date and reminder_dt <= now:
                reminder_dt += timedelta(days=1)

            reminder_at = reminder_dt.isoformat(timespec="seconds")
            due_date = reminder_dt.date().isoformat()

    return {
        "task": task,
        "kind": "reminder" if reminder_intent else "task",
        "due_date": due_date,
        "deadline": deadline,
        "reminder_at": reminder_at,
        "status": "pending",
        "source_text": original,
    }
