"""Thai time end to end on the backend side (the web page side is utils/time.js).

PostgreSQL keeps the UTC wall clock of the Bangkok time the code writes, SQLite keeps the Bangkok wall clock; both
must leave the API as ISO 8601 with +07:00, and "today" must be the Thai day.
"""
import json
from datetime import datetime, timedelta

import pytest

from tests.v3.test_step5_line import env, _signed  # noqa: F401  (fixture + helper)


def test_a_postgres_style_row_leaves_as_thai_time_with_an_offset(monkeypatch):
    from app.utils.timeutil import iso_th

    monkeypatch.setenv("DB_NAIVE_TIMEZONE", "UTC")
    assert iso_th(datetime(2026, 10, 22, 9, 5, 9)) == "2026-10-22T16:05:09+07:00"
    monkeypatch.setenv("DB_NAIVE_TIMEZONE", "Asia/Bangkok")
    assert iso_th(datetime(2026, 10, 22, 16, 5, 9)) == "2026-10-22T16:05:09+07:00"
    assert iso_th(None) is None


def test_the_thai_day_in_utc_storage_starts_at_17_00_the_evening_before(monkeypatch):
    import pytz
    from app.utils.timeutil import BANGKOK, thai_day_bounds

    monkeypatch.setenv("DB_NAIVE_TIMEZONE", "UTC")
    now = BANGKOK.localize(datetime(2026, 10, 22, 0, 30))        # 00:30 Thai = 17:30 UTC the day before
    start, end = thai_day_bounds(now)
    assert start == datetime(2026, 10, 21, 17, 0)
    assert end == datetime(2026, 10, 22, 16, 59, 59, 999999)
    monkeypatch.setenv("DB_NAIVE_TIMEZONE", "Asia/Bangkok")
    start, end = thai_day_bounds(now)
    assert start == datetime(2026, 10, 22, 0, 0)
    assert end == datetime(2026, 10, 22, 23, 59, 59, 999999)


def test_the_api_sends_notification_times_with_an_offset(env):
    from app.models.notification_history import NotificationHistory

    env.monkeypatch.setenv("DB_NAIVE_TIMEZONE", "UTC")
    with env.app.app_context():
        row = NotificationHistory(camera_id=env.camera_id, sent_at=datetime(2026, 10, 22, 9, 5, 9),
                                  detection_type="fall_red", acknowledged_at=datetime(2026, 10, 22, 9, 7, 0))
        env.db.session.add(row)
        env.db.session.commit()
    rows = env.client.get("/api/detection-logs/notifications", headers=env.admin).get_json()
    assert rows[0]["sent_at"] == "2026-10-22T16:05:09+07:00"
    assert rows[0]["acknowledged_at"] == "2026-10-22T16:07:00+07:00"


def test_todays_logs_follow_the_thai_day(env):
    from app.models.detection_log import DetectionLog
    from app.utils.timeutil import BANGKOK, storage_tz

    now_th = datetime.now(BANGKOK)
    start_of_thai_day = BANGKOK.localize(datetime(now_th.year, now_th.month, now_th.day))
    with env.app.app_context():
        inside = start_of_thai_day.astimezone(storage_tz()).replace(tzinfo=None)   # first second of the Thai day
        outside = inside - timedelta(seconds=1)                                    # one second before it
        for ts in (inside, outside):
            env.db.session.add(DetectionLog(camera_id=env.camera_id, timestamp=ts, detection_result="x",
                                            confidence_score=0.5, camera_name="cam", room_name="room"))
        env.db.session.commit()
    got = env.client.get("/api/detection-logs", headers=env.admin).get_json()
    assert isinstance(got, list) and len(got) == 1
    assert got[0]["timestamp"].endswith("+07:00")


def test_an_alert_acknowledged_in_line_has_no_user_and_a_thai_time(env):
    from app.services import alert_service
    import app.routes.line as line_routes

    with env.app.app_context():
        nid = alert_service.save_alert_log(env.camera_id, "fall_red", None, confidence=0.9).id
    env.monkeypatch.setattr(line_routes, "_reply", lambda token, messages: None)
    body = json.dumps({"events": [{"type": "postback", "replyToken": "rt", "source": {"type": "user", "userId": "U1"},
                                   "postback": {"data": f"ack={nid}"}}]}).encode()
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body)).status_code == 200
    row = [r for r in env.client.get("/api/detection-logs/notifications", headers=env.admin).get_json()
           if r["id"] == nid][0]
    assert row["acknowledged_by"] is None
    assert row["acknowledged_at"].endswith("+07:00")
    sent = datetime.fromisoformat(row["sent_at"])
    acked = datetime.fromisoformat(row["acknowledged_at"])
    assert 0 <= (acked - sent).total_seconds() < 30            # the same clock for both columns
