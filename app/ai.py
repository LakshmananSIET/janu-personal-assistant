from __future__ import annotations

import json
import os

from openai import OpenAI

SYSTEM_PROMPT = """
You are Janu, a friendly female personal AI assistant for Lakshman.
Speak naturally and simply. Do not sound like a command-line program.
You are continuing an ongoing conversation, so use the conversation history.
If the user adds information to a previous task, connect it to that task
instead of creating a separate unrelated task. Example:
User: "Tomorrow I need to finish VAYU testing."
User: "Before 5 PM."
The second message should understand the earlier VAYU task and produce one
complete task with tomorrow and a 17:00 deadline.
Extract tasks when the user asks to remember, schedule, finish, or do something.
For task dates use YYYY-MM-DD when known. Use null when not clearly known.
For deadlines use HH:MM in 24-hour format when known.
For a task, make the task text concise and useful.
Return only valid JSON matching the requested schema.
"""

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["chat", "create_task", "list_tasks", "complete_task"]
        },
        "task": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"]},
        "task_id": {"type": ["integer", "null"]},
        "reply": {"type": "string"},
    },
    "required": ["intent", "task", "due_date", "deadline", "task_id", "reply"],
    "additionalProperties": False,
}


def get_ai_result(message: str, history: list[dict[str, str]] | None = None) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key)
    conversation = list(history or [])
    conversation.append({"role": "user", "content": message})

    response = client.responses.create(
        model=os.getenv("JANU_MODEL", "gpt-5.6-luna"),
        instructions=SYSTEM_PROMPT,
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
