from __future__ import annotations

from datetime import datetime, timedelta
import re


def parse_task(text: str) -> dict | None:
    """Small rule-based parser for the first Janu trial.

    The production version will replace this with the AI model's structured
    output. This parser deliberately does not guess a date when one is absent.
    """
    lower = text.lower().strip()

    task_match = re.search(
        r"(?:need to|have to|must|should|finish|complete|do)\\s+(.+?)(?=\\s+(?:before|by|tomorrow|today|on)\\b|$)",
        lower,
    )

    has_task_signal = any(
        phrase in lower
        for phrase in ("need to", "have to", "must", "should", "finish", "complete")
    )

    if not has_task_signal:
        return None

    task = task_match.group(1).strip() if task_match else text.strip()
    task = re.sub(r"\\s+", " ", task).strip(" .")

    due_date = None
    if "tomorrow" in lower:
        due_date = (datetime.now() + timedelta(days=1)).date().isoformat()
    elif "today" in lower:
        due_date = datetime.now().date().isoformat()

    deadline = None
    time_match = re.search(r"\\b(?:before|by)\\s+(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)?\\b", lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        deadline = f"{hour:02d}:{minute:02d}"

    return {
        "task": task,
        "due_date": due_date,
        "deadline": deadline,
        "status": "pending",
        "source_text": text,
    }
