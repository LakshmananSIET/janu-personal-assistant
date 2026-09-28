from __future__ import annotations

from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook

DATA_DIR = Path("data")
TASK_FILE = DATA_DIR / "janu_trial_tasks.xlsx"

HEADERS = [
    "id", "created_at", "task", "due_date", "deadline", "status", "source_text"
]


def _open():
    DATA_DIR.mkdir(exist_ok=True)
    if TASK_FILE.exists():
        workbook = load_workbook(TASK_FILE)
        sheet = workbook.active
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Tasks"
        sheet.append(HEADERS)
    return workbook, sheet


def save_task(task: dict) -> int:
    workbook, sheet = _open()
    next_id = sheet.max_row
    sheet.append([
        next_id,
        datetime.now().isoformat(timespec="seconds"),
        task.get("task"),
        task.get("due_date"),
        task.get("deadline"),
        task.get("status", "pending"),
        task.get("source_text"),
    ])
    workbook.save(TASK_FILE)
    workbook.close()
    return next_id


def list_tasks(status: str | None = "pending", limit: int = 20) -> list[dict]:
    workbook, sheet = _open()
    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        item = dict(zip(HEADERS, row))
        if status and item["status"] != status:
            continue
        rows.append(item)
    workbook.close()
    return rows[-limit:]


def find_task(task_id: int) -> dict | None:
    workbook, sheet = _open()
    for row in sheet.iter_rows(min_row=2, values_only=True):
        item = dict(zip(HEADERS, row))
        if item["id"] == task_id:
            workbook.close()
            return item
    workbook.close()
    return None


def update_task_status(task_id: int, status: str) -> bool:
    workbook, sheet = _open()
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row, 1).value == task_id:
            sheet.cell(row, 6).value = status
            workbook.save(TASK_FILE)
            workbook.close()
            return True
    workbook.close()
    return False
