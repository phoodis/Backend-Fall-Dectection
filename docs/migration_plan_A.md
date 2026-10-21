# Migration plan A: FRONT_FRIEND (whole set) + backend pieces it needs, Telegram retired

Branch `plan-a`, branched from `v3-migration` (da57763). Decided: use the friend's frontend as a whole
and stop using Telegram. Five steps; each ends with a stop and a report before the next begins.

Out of scope for every step: escalation, still-down, clip_buffer, claim lock / loop token, the friend's
`/detector*` profile panel, `pose_extraction/`, alone-detection internals, yolov10x.

| # | Step | What changes | Done when |
|---|------|--------------|-----------|
| 1 | Keep the v3 loop alive when alerting fails | The alert block of `_process_v3_fall_detection` is wrapped so no exception escapes it; `save_alert_log` runs before the notification; Telegram call replaced by a swappable `notify_fall_alert` (logs only for now) | tests for save / notify / imwrite failures pass; tests/pose + tests/v3 pass; replay of Fall_6 and normal_1 identical to the reference |
| 2 | `/alert-images`, acknowledge, new `notification_history` columns | `routes/alert_images.py`; `POST /detection-logs/notifications/{id}/acknowledge`; columns `acknowledged_at`, `acknowledged_by`, `confidence` (and the response fields the UI reads) added with the `ALTER TABLE` list in `app/__init__.py` | route + migration tests; existing DB gets the columns on start |
| 3 | media-token + stream auth | `POST /stream/camera/{id}/media-token`; `GET /stream/camera/{id}` requires `?t=`; ownership checks on the other stream routes; fail-closed token blocklist; logout must record the revoke | stream refused without a valid token; token scoped to one camera and expires |
| 4 | LINE instead of Telegram | `/line/settings`, `/line/test`, `/line/webhook`; `line_settings` + `line_discovered_targets` tables; `notify_fall_alert` sends to LINE; user-delete cleanup; a cached app instead of `create_app()` per alert | test push works with a real channel; alert still stored when LINE fails |
| 5 | Switch to FRONT_FRIEND | Use `C:\Users\ASUS\FALL_DETECT\frontend` as the frontend; remove the friend's accuracy claims from the UI text (URFD 93% / 75%); proxy target and Firebase env for this setup; `/cameras/test-videos` | UI runs against this backend; no unmeasured number shown |

## Rules for all steps
- Work only on `plan-a`. Never push `master`, never push tags, never force-push, never merge.
- v2 legacy, alone and bed-exit loops are not touched until a step says so.
- Detection results must not change: after any step that touches `camera_manager.py`,
  `tools/v3_eval_via_camera_manager.py` must still reproduce the reference for the checked clips.
- Database changes are additive (new nullable columns / new tables); back up before running on the server.

## Known risks carried by the plan
- The server image (Dockerfile / requirements.txt) is still the old library set, not `constraints-cpu.txt`.
- LINE needs a public HTTPS URL (`PUBLIC_BASE_URL`) and a channel secret for the acknowledge button and for images.
- `/alert-images` is unauthenticated by design (loaded from `<img>` and fetched by LINE); file names are guessable.
- Step 3 changes the stream contract; anything else that opens `/api/stream/camera/{id}` without a token stops working.

## Step 1 notes (done in this commit series)
- Cooldown is consumed when an alert is attempted, not when it succeeds, so a persistent failure cannot retry at
  frame rate; the next attempt is one cooldown later.
- `save_alert_log` swallows its own errors and returns False without rolling back; the loop therefore rolls back
  whenever it returns a falsy value (since step 2 `save_alert_log` also rolls back by itself).
- Not covered by step 1: `save_detection_log` (periodic log) and `db.session.refresh(camera)` still end the loop if the
  database itself is down.

## Backlog (noted, not scheduled)
- **Real-loop speed on the server (step 1 test, 2026-10):** the live loop ran about 6.9 fps against the 8 fps
  evaluation target, and the worker log says the pose model uses 1 CPU thread. Look at thread settings
  (`OMP_NUM_THREADS=1` and the 2-CPU limit in `docker-compose.yml`, torch thread count) before trusting the
  evaluated numbers on that machine. The evaluation was measured with 4 threads at ~9.9 fps.

## Security note: `/api/alert-images/<filename>` has no login (step 2)
The route is copied from the friend's backend and, like it, has **no JWT**. The web UI loads pictures with
`<img>` / `<video>`, which cannot send an `Authorization` header, and LINE (step 4) must fetch them from a public
URL. The consequence is plain: **anyone who can guess a file name can open the picture.** Names are
`v3_fall_detect_<camera id>_<unix seconds>.jpg`, so a person who knows a camera id and roughly when something
happened can enumerate them. What the route does limit: it serves only a single plain file name (no `/`, `\`,
`..`, hidden files, NUL), only `.jpg .jpeg .png .webp .mp4`, only files that really sit in `ALERT_IMAGE_DIR`
(symlinks resolved), with `X-Content-Type-Options: nosniff`. It does not hide that a file exists from someone who
guesses right. Options if that is not acceptable: random file names (a token in the name), signed short-lived URLs
like the live-view media token (step 3), or requiring login and giving the UI a fetch-with-header path.

## Step 2 notes
- Columns added to `notification_history` (all nullable, existing rows get NULL): `confidence`, `acknowledged_at`,
  `acknowledged_by` (FK users), `escalation_count`, `clip_path`, `still_down_seconds`. `app/db_migrate.py` adds
  them with `ALTER TABLE ... ADD COLUMN` (`IF NOT EXISTS` on PostgreSQL), checks first, never touches data and
  can run any number of times. It also still adds `users.telegram_chat_id`. The PostgreSQL branch is only
  exercised on the server (no PostgreSQL available where this was developed; SQLite is covered by tests).
- Acknowledge: `POST /api/detection-logs/notifications/<id>/acknowledge`. A user may acknowledge alerts of their own
  cameras (otherwise 403), an admin any alert; unknown id is 404. The write is one conditional UPDATE
  (`WHERE acknowledged_at IS NULL`), so the first acknowledgement wins and a later one answers 200 with the first
  person's values. Same permission rule as the friend's route.
- `GET /api/detection-logs/notifications[/<camera_id>]` now return `confidence`, `acknowledged_at`,
  `acknowledged_by`, `escalation_count` (0 when NULL), `still_down_seconds`, `still_down_threshold` (from
  `STILL_DOWN_SECONDS`, default 10, only so the UI uses the same number) and `clip_path`.
- `save_alert_log` takes `confidence`, returns the saved row (or False) and rolls back on failure. The v3 loop stores
  its probability there.
- Deleting an admin who acknowledged alerts clears `acknowledged_by` first (foreign key). Deleting a user who still
  owns cameras already failed before this step (500) and is not changed.

## Step 2: testing on the server with curl
Replace `BASE` (e.g. `http://localhost:8932`), the passwords, and the ids. After pulling `plan-a`, restart the backend
AND the worker once: the start-up log must show `Added missing column ... to notification_history table` six times the
first time and nothing on later starts.

```bash
BASE=http://localhost:8932

# 1. log in (admin shown; use a normal user to check the permission rule)
TOKEN=$(curl -s -X POST $BASE/api/auth/login -H 'Content-Type: application/json'   -d '{"username":"admin","password":"<password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. notifications: every item must carry confidence, acknowledged_at, acknowledged_by, escalation_count,
#    still_down_seconds, still_down_threshold, clip_path (old rows: null / 0)
curl -s $BASE/api/detection-logs/notifications -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -40

# 3. acknowledge one (use an id from step 2). 200 + acknowledged_at/acknowledged_by.
curl -s -X POST $BASE/api/detection-logs/notifications/<ID>/acknowledge -H "Authorization: Bearer $TOKEN"
#    again: 200 with the SAME values as the first answer
curl -s -X POST $BASE/api/detection-logs/notifications/<ID>/acknowledge -H "Authorization: Bearer $TOKEN"
#    without a token: 401; another user's alert as a normal user: 403; unknown id: 404
curl -s -o /dev/null -w '%{http_code}
' -X POST $BASE/api/detection-logs/notifications/<ID>/acknowledge

# 4. picture: file name = basename of image_path from step 2. No token needed. 200 image/jpeg
curl -s -o /tmp/alert.jpg -w '%{http_code} %{content_type}
' $BASE/api/alert-images/<FILENAME>.jpg
#    must be refused (404): traversal, other extensions, missing files
curl -s -o /dev/null -w '%{http_code}
' --path-as-is "$BASE/api/alert-images/../app/config.py"
curl -s -o /dev/null -w '%{http_code}
' "$BASE/api/alert-images/..%2f..%2fetc%2fpasswd"
curl -s -o /dev/null -w '%{http_code}
' $BASE/api/alert-images/does-not-exist.jpg
```

If the backend runs in Docker, `ALERT_IMAGE_DIR` (default `/app/tmp`) must be the same mounted folder for the API and
the worker, otherwise the worker writes pictures the API cannot see.

Check the database on the server (PostgreSQL) after two restarts:
`\d notification_history` lists the six new columns once each, and
`SELECT count(*) FROM notification_history;` is unchanged.
