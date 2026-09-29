from app.task_parser import parse_task


def test_explicit_task_keyword():
    result = parse_task("task: go shopping at 6 PM")
    assert result is not None
    assert result["task"] == "go shopping"
    assert result["reminder_at"] is None


def test_explicit_reminder():
    result = parse_task("remind me to go shopping at 6 PM")
    assert result is not None
    assert result["task"] == "go shopping"
    assert result["reminder_at"] is not None


def test_normal_sentence_is_not_task():
    assert parse_task("I need to finish VAYU testing") is None
    assert parse_task("Please do the testing") is None


def test_negative_reminder_is_not_task():
    assert parse_task("No no, don't remind me") is None


def test_tomorrow_deadline_with_explicit_task():
    result = parse_task("task: tomorrow finish VAYU testing before 5 PM")
    assert result is not None
    assert result["task"] == "finish vayu testing"
    assert result["deadline"] == "17:00"
    assert result["due_date"] is not None
