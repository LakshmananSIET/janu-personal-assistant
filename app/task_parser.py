from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


def _is_negated(text: str, keyword: str) -> bool:
    """Ignore phrases such as 'don't remind me' and 'no reminder'."""
    match = re.search(rf"\b{re.escape(keyword)}\b", text)
    if not match:
        return False
    prefix = text[max(0, match.start() - 35):match.start()]
    return bool(re.search(r"\b(?:no|not|don't|dont|do not|never)\b", prefix))


def parse_task(text: str) -> dict | None:
    """Create a task only when the user explicitly says 'task' or asks to be reminded."""
    original = text.strip()
    lower = original.lower()

    reminder_phrase = re.search(r"\bremind\s+me\b", lower)
    reminder_word = re.search(r"\breminder\b", lower)
    task_word = re.search(r"\btask\b", lower)
    reminder_intent = bool(reminder_phrase or reminder_word)
    task_intent = bool(task_word and not reminder_intent)

    # Normal conversation must stay normal conversation.
    # Words such as "need", "finish", "complete", "do", etc. are NOT task triggers.
    if not task_intent and not reminder_intent:
        return None

    # Do not create a task from a negative request such as "no, don't remind me".
    if reminder_phrase and _is_negated(lower, "remind"):
        return None
    if reminder_word and _is_negated(lower, "reminder"):
        return None
    if task_intent and re.search(r"\b(?:no\s+task|not\s+(?:a\s+)?task|don\'t\s+(?:add|create|make)\s+(?:a\s+)?task|do\s+not\s+(?:add|create|make)\s+(?:a\s+)?task)\b", lower):
        return None

    # Extract the actual task text.
    if reminder_phrase:
        # Handle both common forms:
        # "remind me to call Arun at 6 PM"
        # "remind me at 6 PM to call Arun"
        marker = reminder_phrase.end()
        suffix = lower[marker:].strip(" ,")
        prefix = lower[:reminder_phrase.start()].strip(" ,")
        time_in_suffix = re.search(
            r"\b(?:at|before|by)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
            suffix,
        )

        if time_in_suffix:
            before_time = suffix[:time_in_suffix.start()].strip(" ,")
            after_time = suffix[time_in_suffix.end():].strip(" ,")
            # If the user repeats "remind me" at the end, ignore that
            # trailing conversational instruction.
            after_time = re.split(r"\s+remind\s+me\b", after_time, maxsplit=1)[0].strip(" ,")
            before_time = re.sub(r"^(?:to\s+)?(?:tomorrow|today)\b\s*", "", before_time).strip()
            if before_time and before_time not in {"to", "tomorrow", "today"}:
                task = re.sub(r"^to\s+", "", before_time).strip()
            elif after_time:
                task = re.sub(r"^(?:to\s+)?(?:tomorrow|today)\b\s*", "", after_time).strip()
            elif prefix:
                task = prefix
            else:
                task = suffix
        else:
            task = re.sub(r"^to\s+", "", suffix).strip() or prefix or original
    elif reminder_word:
        reminder_match = re.search(
            r"\breminder\b\s*(?:to|for|about|:|-)?\s*(.+?)(?=\s+(?:at|on|tomorrow|today|before|by)\b|$)",
            lower,
        )
        task = reminder_match.group(1).strip() if reminder_match and reminder_match.group(1).strip() else original
    else:
        # Explicit "task" keyword, e.g. "task: go shopping at 6 PM".
        task_match = re.search(r"\btask\b\s*[:\-]?\s*(.*)$", lower)
        task = task_match.group(1).strip() if task_match and task_match.group(1).strip() else original
        task = re.sub(r"^(?:create|add|make|take)\s+(?:a\s+)?task\s*[:\-]?\s*", "", task).strip()

    # Remove scheduling words from the stored task title.
    task = re.sub(r"\b(?:tomorrow|today)\b", "", task)
    task = re.sub(r"\s+(?:at|before|by)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b.*$", "", task)
    task = re.sub(r"\s+", " ", task).strip(" .,:-")
    if not task:
        return None

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

        # Only reminder language schedules an actual notification.
        if reminder_intent:
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
        "kind": "reminder" if reminder_intent else "task",
        "due_date": due_date,
        "deadline": deadline,
        "reminder_at": reminder_at,
        "status": "pending",
        "source_text": original,
    }
