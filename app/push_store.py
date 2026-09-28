from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

DATA_DIR=Path("data")
FILE=DATA_DIR/"janu_push_subscriptions.json"
_lock=Lock()


def _load():
    if not FILE.exists():
        return []
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save_subscription(subscription: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        items=_load()
        endpoint=subscription.get("endpoint")
        items=[x for x in items if x.get("endpoint") != endpoint]
        items.append(subscription)
        FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def remove_subscription(endpoint: str) -> None:
    with _lock:
        items=[x for x in _load() if x.get("endpoint") != endpoint]
        DATA_DIR.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def list_subscriptions() -> list[dict]:
    with _lock:
        return list(_load())
