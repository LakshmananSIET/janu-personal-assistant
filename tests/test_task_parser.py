from app.task_parser import parse_task


def test_tomorrow_deadline():
    result = parse_task("Tomorrow I need to finish VAYU testing before 5 PM")
    assert result is not None
    assert result["task"] == "vayu testing"
    assert result["deadline"] == "17:00"
    assert result["due_date"] is not None


def test_non_task():
    assert parse_task("What is the weather?") is None
