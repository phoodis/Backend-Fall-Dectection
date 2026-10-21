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
  whenever it returns a falsy value.
- Not covered by step 1: `save_detection_log` (periodic log) and `db.session.refresh(camera)` still end the loop if the
  database itself is down.
