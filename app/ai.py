from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

SYSTEM_PROMPT = """
You are Janu, a friendly female personal AI assistant for Lakshman.
Speak naturally and simply. Use conversation history.
If the user adds information to a previous task, connect it to that task.
Extract tasks when the user asks to remember, schedule, finish, or do something.
If the user asks for a reminder, create the task and set reminder_at.
Use ISO 8601 with Asia/Kolkata offset for reminder_at when a time is known.
The current local time is supplied below; use it to resolve today/tomorrow.
For task dates use YYYY-MM-DD. For deadlines use HH:MM.
Do not invent missing dates or times. Return only the requested JSON.
"""

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["chat", "create_task", "list_tasks", "complete_task"]},
        "task": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"]},
        "reminder_at": {"type": ["string", "null"]},
        "task_id": {"type": ["integer", "null"]},
        "reply": {"type": "string"},
    },
    "required": ["intent", "task", "due_date", "deadline", "reminder_at", "task_id", "reply"],
    "additionalProperties": False,
}


def get_ai_result(message: str, history: list[dict[str, str]] | None = None) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    instructions = SYSTEM_PROMPT + f"\nCurrent Asia/Kolkata time: {now}"

    client = OpenAI(api_key=api_key)
    conversation = list(history or [])
    conversation.append({"role": "user", "content": message})

    response = client.responses.create(
        model=os.getenv("JANU_MODEL", "gpt-5.6-luna"),
        instructions=instructions,
        input=conversation,
        text={
            "format": {
                "type": "json_schema",
                "name": "janu_result",
                "strict": True,
                "schema": TASK_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)
