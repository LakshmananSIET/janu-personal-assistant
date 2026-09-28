from __future__ import annotations

import json
import os

from openai import OpenAI


SYSTEM_PROMPT = """
You are Janu, a friendly female personal AI assistant for Lakshman.
Speak naturally and simply. Do not sound like a command-line program.
Extract tasks when the user is asking to remember, schedule, finish, or do something.
Use null when a date or deadline is not clearly provided.
Return only valid JSON matching the requested schema.
"""

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_task": {"type": "boolean"},
        "task": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"]},
        "reply": {"type": "string"},
    },
    "required": ["is_task", "task", "due_date", "deadline", "reply"],
    "additionalProperties": False,
}


def get_ai_result(message: str) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=os.getenv("JANU_MODEL", "gpt-5.6-luna"),
        instructions=SYSTEM_PROMPT,
        input=message,
        text={
            "format": {
                "type": "json_schema",
                "name": "janu_task_result",
                "strict": True,
                "schema": TASK_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)
