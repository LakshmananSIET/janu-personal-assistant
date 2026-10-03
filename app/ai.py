from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

logger = logging.getLogger("jaanu.ai")

SYSTEM_PROMPT = """
You are Jaanu, a friendly female personal AI assistant for Lakshman.

LANGUAGE:
- Speak naturally in Tanglish: conversational Tamil written in English letters, mixed with English where natural.
- Understand Tamil, Tanglish and English.
- Reply in the same language/style as the user.
- Never use formal/textbook Tamil unless the user asks.
- Keep spoken replies short, natural and warm.
- Use natural Tanglish like normal Chennai/Tamil conversation: Tamil words in English letters mixed with common English words.
- Keep replies simple and conversational; avoid robotic or textbook wording.
- Use "Lakshman sir" naturally when addressing Lakshman, but do not repeat "sir" in every sentence.
- Prefer phrases like "Seri", "Aama", "Sure", "Okay", "Panren", "Panniten", "Venumna", "Enna help venum?" when they fit the context.
- Return `reply` in natural Tanglish (Tamil written in English letters).
- Return `tts_text` as the same reply rewritten in natural Tamil script for a Tamil female TTS voice. Keep common English technical/product words in English when that sounds natural.
- Example: reply = "Sure Lakshman! Naalaikku morning 9 manikku production report remind panren." tts_text = "சரி லக்ஷ்மன்! நாளைக்கு காலை 9 மணிக்கு production report remind பண்றேன்."

TASK/REMINDER INTENT:
- Understand natural Tanglish such as "task add pannu", "oru task note pannu", "remind pannu", "nyabagam paduthu", and "naalaikku remind pannu".
- Create a task when the user clearly asks to add/note a task.
- Create a reminder when the user clearly asks to be reminded/nyabagam padutha.
- Normal conversation remains "chat".
- Do not create a task or reminder from a normal statement unless the user clearly asks for one.
- Do not create a reminder when the user rejects it, such as "vendam, remind panna vendam".
- If important information is missing, ask one short clarification.
- Use ISO 8601 with Asia/Kolkata offset for reminder_at when a time is known.
- For task dates use YYYY-MM-DD. For deadlines use HH:MM.
- Do not invent missing dates or times.

Return only the requested JSON.
"""

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["chat", "create_task", "create_reminder", "list_tasks", "complete_task"]},
        "task": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"]},
        "reminder_at": {"type": ["string", "null"]},
        "task_id": {"type": ["integer", "null"]},
        "reply": {"type": "string"},
        "tts_text": {"type": "string"},
    },
    "required": ["intent", "task", "due_date", "deadline", "reminder_at", "task_id", "reply"],
    "additionalProperties": False,
}


def _fallback_result() -> dict:
    return {
        "intent": "chat",
        "task": None,
        "due_date": None,
        "deadline": None,
        "reminder_at": None,
        "task_id": None,
        "reply": "Sorry, free AI service connect aagala. Konjam later try pannunga.",
        "tts_text": "சாரி, free AI service connect ஆகல. கொஞ்சம் later try பண்ணுங்க.",
    }


def _gemini_result(message: str, history: list[dict[str, str]] | None = None) -> dict | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY is missing")
        return None

    try:
        from google import genai
        from google.genai import types

        now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
        contents = []
        for item in history or []:
            role = "model" if item.get("role") == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=str(item.get("content", "")))],
                )
            )
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )
        )

        model = os.getenv("JANU_AI_MODEL", "gemini-3.7-flash")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + f"\nCurrent Asia/Kolkata time: {now}",
                response_mime_type="application/json",
                response_schema=TASK_SCHEMA,
                temperature=0.7,
            ),
        )

        if not response.text:
            logger.error("Gemini returned an empty response (model=%s)", model)
            return None

        return json.loads(response.text)
    except Exception as exc:
        logger.exception("Gemini request failed: %s", exc)
        return None


def _openai_result(message: str, history: list[dict[str, str]] | None = None) -> dict | None:
    if os.getenv("JANU_USE_OPENAI", "false").lower() not in {"1", "true", "yes", "on"}:
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
        conversation = list(history or [])
        conversation.append({"role": "user", "content": message})
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=os.getenv("JANU_MODEL", "gpt-5.6-luna"),
            instructions=SYSTEM_PROMPT + f"\nCurrent Asia/Kolkata time: {now}",
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
    except Exception as exc:
        logger.exception("OpenAI request failed: %s", exc)
        return None


def get_ai_result(message: str, history: list[dict[str, str]] | None = None) -> dict | None:
    result = _gemini_result(message, history)
    if result is not None:
        return result

    result = _openai_result(message, history)
    if result is not None:
        return result

    return None
