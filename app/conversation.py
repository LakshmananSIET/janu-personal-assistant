from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock

MAX_TURNS = 12
_sessions: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=MAX_TURNS * 2))
_lock = Lock()


def add_message(session_id: str, role: str, content: str) -> None:
    if not session_id:
        return
    with _lock:
        _sessions[session_id].append({"role": role, "content": content})


def get_history(session_id: str) -> list[dict[str, str]]:
    if not session_id:
        return []
    with _lock:
        return list(_sessions.get(session_id, []))


def clear_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
