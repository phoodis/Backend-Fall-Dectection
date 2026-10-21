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
| 4 | Switch to FRONT_FRIEND (moved up from 5: step 3 breaks the old frontend's live view, which sends the login JWT in the URL) | Use `C:\Users\ASUS\FALL_DETECT\frontend` as the frontend; remove the friend's accuracy claims from the UI text (URFD 93% / 75%); proxy target and Firebase env for this setup; `/cameras/test-videos` | UI runs against this backend, live view works with media tokens; no unmeasured number shown |
| 5 | LINE instead of Telegram (moved down from 4) | `/line/settings`, `/line/test`, `/line/webhook`; `line_settings` + `line_discovered_targets` tables; `notify_fall_alert` sends to LINE; user-delete cleanup; a cached app instead of `create_app()` per alert | test push works with a real channel; alert still stored when LINE fails |

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
- Step 3 changes the stream contract; anything else that opens `/api/stream/camera/{id}` without a media token stops working.
  **Between step 3 and step 4 the old frontend (FRONT_ME) cannot show the live view** (it sends the login JWT as `?token=`); do not deploy step 3 to users before step 4 (step 4 is the frontend that sends the media token).

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

## Step 3 notes: media token + stream auth
Ported from the friend's backend: `app/services/media_token.py` and `app/services/authz.py` (copied as they are),
the stream routes' authorisation, the fail-closed `TokenBlocklist` and the logout checks. Tests:
`tests/v3/test_step3_stream_auth.py`.

**Media token** (`POST /api/stream/camera/<id>/media-token`, login required, owner or admin): signed with `itsdangerous`
under its own salt (not a JWT, so it cannot be used as a bearer token and a JWT cannot be used as one); binds user id,
camera id and the session's access-token `jti`. It can only START a view for 60 s (`START_SECONDS`); a view lasts at most
600 s (`STREAM_MAX_SECONDS`), then the server ends it and the client asks for a new token. At connect time the server
re-checks everything: signature and age, user still exists, user still owns the camera (or is admin), the camera exists,
and the session has not been logged out. `t=` / `token=` values are redacted from werkzeug / gunicorn access logs.
The login JWT in the URL (`?token=`) is **not read any more**; the request gets 401. The live view carries no CORS headers.
Signing uses `SECRET_KEY` (a warning is printed while it is the default `dev`): **set a long random `SECRET_KEY` on the server.**

### Who can reach each stream route (before -> after)
Before, `get_current_user_id()` swallowed every JWT problem and returned None, and `None` meant "any camera":
a request with no token, a bad token, an expired or a logged-out token was treated the same as anonymous.

| Route | Before step 3 | After step 3 |
|---|---|---|
| `GET /stream/camera/<id>` (MJPEG) | **Anyone**, no login, any camera (the `?token=` JWT was never read) | Only a holder of a media token (`?t=`) for THAT camera, issued to its owner or an admin; 401 otherwise |
| `POST /stream/camera/<id>/media-token` | did not exist | Login + owner of the camera or admin; someone else's camera 403, unknown 404 |
| `POST /stream/camera/<id>/start` | **Anyone**, any camera | Login + owner or admin (403 / 404) |
| `POST /stream/camera/<id>/stop` | **Anyone**, any camera | Login + owner or admin |
| `GET /stream/camera/<id>/status` | **Anyone**, any camera | Login + owner or admin |
| `GET /stream/camera/<id>/test` | **Anyone**, any camera; the reply contains the camera URL (may hold RTSP credentials) and grabs a frame | Login + owner or admin |
| `GET /stream/stats` | **Anyone**: no login = every camera's streams; logged in = own cameras, plus `total_system_streams` (all streams on the box) | Login; a user sees their own cameras, an admin all cameras; `total_system_streams` removed |
| `POST /stream/cleanup` | **Anyone** (stops inactive streams of every user) | Admin only |

Not under `/stream` and not changed: `GET /videos/<filename>` in `app/__init__.py` still serves `/app/videos` with no login.

### Logout, `/auth/refresh`, `/auth/logout-all` (what actually changes)
- Changed (friend's version): `TokenBlocklist.is_jti_blacklisted` and the JWT blocklist loader in `create_app` now fail CLOSED
  (a database fault makes a token count as revoked instead of valid); `/auth/logout` and `/auth/logout-all` answer 500
  "Logout could not be recorded; the session is still valid." when the revocation could not be stored, instead of 200.
- Effect on the media token: it is bound to the access token's `jti`, so logging out kills it at once (tested).
- **Known gap, same in the friend's backend, not fixed here:** the browser calls logout with the access token only, so the
  login's REFRESH token stays valid until it expires (7 days) and `POST /auth/refresh` still returns a new access token
  (and therefore new media tokens). `/auth/logout-all` also revokes only the token it is called with; another login of
  the same user stays valid. Both behaviours are pinned by tests named `..._known_gap`. A real fix needs either the
  frontend to send the refresh token on logout, or a session id claim / per-user "valid after" time on the server.
- `/auth/refresh` itself is untouched; with a fail-closed blocklist it is refused as well when the database cannot be read.

### Not ported (belongs to other friend features) and what was cut
- The pose-skeleton overlay (`?overlay=1`, `draw_overlay` in `stream_service`): the parameter is ignored here, so the
  frontend's "show boxes" toggle does nothing until it is decided what the preview should draw.
- `wait_for_new_frame` pacing, RTSP-over-TCP option, `/app/Test` paths in `stream_service` (friend's other changes).
- The `PUBLIC_EDGE_PREFIXES` filter in `create_app` (only for the public LINE tunnel; belongs to the LINE step).
- Detector profile routes, claim lock / loop token, escalation, still-down, clip buffer: none were needed.
- `admin.py` keeps its own `admin_required`; only `stream.py` uses `authz.admin_required`.
- Two deliberate differences from the friend's stream routes: someone else's camera answers **403** (unknown camera 404; the
  friend answers 404 for both), and an admin sees all cameras in `/stream/stats` (the friend shows an admin only their own).

### Step 3: testing on the server with curl
```bash
BASE=http://localhost:8932
login() { curl -s -X POST $BASE/api/auth/login -H 'Content-Type: application/json' -d "{\"username\":\"$1\",\"password\":\"$2\"}"; }
TOKEN=$(login admin '<password>' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
CAM=<camera id>

# 1. ask for a media token (login needed), then open the stream with it. Expect 200 and multipart/x-mixed-replace
MT=$(curl -s -X POST $BASE/api/stream/camera/$CAM/media-token -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -m 5 -o /tmp/mjpeg.bin -w '%{http_code} %{content_type}\n' "$BASE/api/stream/camera/$CAM?t=$MT"; head -c 200 /tmp/mjpeg.bin | strings | head -3

# 2. refused cases (all must print 401)
curl -s -o /dev/null -w 'no token:      %{http_code}\n' "$BASE/api/stream/camera/$CAM"
curl -s -o /dev/null -w 'JWT in URL:    %{http_code}\n' "$BASE/api/stream/camera/$CAM?token=$TOKEN"
curl -s -o /dev/null -w 'JWT as t=:     %{http_code}\n' "$BASE/api/stream/camera/$CAM?t=$TOKEN"
curl -s -o /dev/null -w 'start no auth: %{http_code}\n' -X POST $BASE/api/stream/camera/$CAM/start
curl -s -o /dev/null -w 'stats no auth: %{http_code}\n' $BASE/api/stream/stats
sleep 65; curl -s -o /dev/null -w 'expired t:     %{http_code}\n' "$BASE/api/stream/camera/$CAM?t=$MT"     # 60 s to start a view

# 3. another user: log in as a normal user who does NOT own $CAM -> 403 for media-token/start/stop/status/test, cleanup
UT=$(login <user> '<password>' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -w ' %{http_code}\n' -X POST $BASE/api/stream/camera/$CAM/media-token -H "Authorization: Bearer $UT"     # 403
curl -s -w ' %{http_code}\n' -X POST $BASE/api/stream/cleanup -H "Authorization: Bearer $UT"                      # 403

# 4. a token for camera A does not open camera B (use another camera id $OTHER) -> 401
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/stream/camera/$OTHER?t=$MT"

# 5. logout kills the session and its media tokens -> 200, then 401 / 401
MT2=$(curl -s -X POST $BASE/api/stream/camera/$CAM/media-token -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST $BASE/api/auth/logout -H "Authorization: Bearer $TOKEN"
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/stream/camera/$CAM?t=$MT2"
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/auth/verify -H "Authorization: Bearer $TOKEN"
```
The server log must not show the `t=` value (it prints `t=REDACTED`). In a browser the live view works only through the
frontend that asks for the token first (step 4); opening the stream URL by hand needs a token from step 1.

## Step 4 notes: FRONT_FRIEND moved in, live view reshaped, test videos
**Where the frontend lives:** `frontend/` in this repository (option A, decided by the owner). Copied from the friend's repository
`C:\Users\ASUS\FALL_DETECT`, tracked files only (`git archive`), friend's HEAD `5fb74d0`; the frontend was last changed there by
`de7b003` ("Full system test 8 Oct: per-user LINE id, user delete, old-vs-new report"). No `node_modules`, `dist` or `.env` is in git
(`frontend/.gitignore` has them; `npm ci` makes `node_modules`; `.env` is created by hand from `.env.example`). The old frontend
`FRONT_END_DETR_BED-main` was not touched and stays as the backup.

**Changed in the copy (everything else is the friend's file as it was):**
| File | Change |
|---|---|
| `src/utils/detectionType.js` | URFD 93% / 75% / 45% and the other measured figures removed from the camera-form help text and from comments; the help now only says YOLO-pose v3 is recommended and that an alert asks for a check, it does not confirm a fall |
| `src/views/MonitorView.vue` | the 95% / 88% figures in a CSS comment removed |
| `src/views/AboutView.vue` | the "detector now running" and "change detector profile" panels (and their script) cut: they call `/detector` and `/detector/profiles`, which belong to the detector-profile feature that is out of scope; the page would have shown errors |
| `vite.config.js` | proxy target from `VITE_PROXY_TARGET` (default `http://127.0.0.1:8932`) instead of the fixed Docker name `http://backend:8932`; works on the host, through an SSH tunnel and inside Docker |
| `.env.example` | documented; `VITE_API_BASE_URL=/api` + `VITE_PROXY_TARGET`; Firebase keys empty |
| `src/services/streamService.js` | the live-view URL is built against `window.location`, so the relative `/api` base works; reads `overlay_available` |
| `src/components/common/MediaViewer.vue` | a small note when the skeleton was requested but the server has it switched off |
| `src/services/lineService.js`, `src/views/NotificationSettingsView.vue` | a 404 from `/line/*` shows "LINE notifications are not enabled on this system yet" instead of an error; the form is hidden until step 5 brings the routes (the page then works with no further change) |
| `CameraEditModal.vue`, `CameraManagementView.vue`, `cameraService.js`, `testVideos.js` | no `/app/Test` or `Test/` in code or text; the edit dialog opens on the dropdown when the camera's url is one of the listed videos |
| `README.md` | connection and Docker notes |

**Firebase:** the friend's `config/firebase.js` and `services/firebaseAuthService.js` already contain the same guard as the owner's
patches on the old frontend (no key -> `auth` is null, Google sign-in reports "not configured", the app still starts) and a bit more
(`isSupported` for analytics), so the friend's versions are used as they are. The real Firebase values stay in a private
`frontend/.env` (copy the `VITE_FIREBASE_*` lines from the old frontend's `.env`); they are never in git.

**What the friend's UI shows that this backend does not send yet** (harmless, nothing was cut): the "re-sent" and "still down" badges
need `escalation_count > 0` / `still_down_seconds`, which are 0 / null here, so they never show.

### Live view: what it was, what it is now (backend)
Found while measuring (`tools/stream_bench.py`, `tools/stream_bench_matrix.py`): the step-3 live view
(1) ran the YOLO person detector on **every** frame it sent (`get_mjpeg_frame()` defaulted to `draw_bbox=True`, an old always-on
overlay), in the web process, and (2) had **no pacing**: it re-encoded the newest frame in a tight loop, many times per captured
frame. (2) is what produced the 49 MB in 5 s (~10 MB/s) seen on the server; (1) is a hidden CPU cost that competes with the detector
when both run on one host.

Now (`app/services/stream_service.py`, settings in `app/config.py`, all from environment variables / `.env`):
| Setting | Default | Meaning |
|---|---|---|
| `STREAM_MAX_SIDE` | 640 | longest side in pixels (0 = do not resize). Was: width capped at 640, so an upright phone video went out 640 x 1138 |
| `STREAM_JPEG_QUALITY` | 70 | was 80 |
| `STREAM_FPS` | 10 | most frames per second to one viewer (0 = no cap); also one frame per captured frame at most |
| `STREAM_OVERLAY_ENABLED` | false | may a viewer ask for the skeleton (`?overlay=1`)? |
| `STREAM_OVERLAY_INFER_EVERY` | 6 | pose model on every Nth frame sent, the others reuse the last result |
| `TEST_VIDEO_DIR` | `/app/videos` | folder listed by `GET /api/cameras/test-videos` |

Nothing here reaches the detector: the preview has its own `VideoCapture`; `get_mjpeg_frame` works on a copy; the detector code
(`camera_manager.py`, `v3_fall_detection.py`) was not changed, so the replay parity result of step 1 stands (not re-run).

**Overlay (skeleton):** `?overlay=1` + `_draw_pose_skeleton` ported from the friend, with three changes: it draws on the already
shrunk picture (cheaper); one lock serialises the pose model across viewers and the model's remembered person crop is cleared before
each call (the model object is shared by every camera's preview and the crop would belong to another camera); and the old
person-box drawing (`_draw_person_bboxes`) is gone. It runs in the **web** process (a second copy of the pose model is loaded there on
first use), not in the celery worker. **Default off** (`STREAM_OVERLAY_ENABLED=false`) because it did not leave the worker's speed
alone in the measurements below; the UI toggle was already off by default and says so when the server has it off.

### Measurements (this laptop, NOT the server -- repeat there)
Clip Fall_6 (1080 x 1920 upright, 30 fps), CPU, detector = the v3 loop at the evaluated profile, 1 torch thread, worker and viewer
as two processes **pinned to the same 4 logical CPUs** to make them compete. Viewer figures are for one viewer, 20 s.
| Live view alone | frames/s sent | KB/frame | MB/s | CPU (100 = one core) |
|---|---|---|---|---|
| before (step 3 code, person detector working) | 1.7 | 112 | 0.19 | 353 |
| after, defaults (640 / q70 / 10 fps) | 9.5 | 38 | 0.36 | 15 |
| after + overlay | 8.2 - 8.8 | 43 | 0.35 - 0.38 | 32 - 47 |

The laptop's "before" is slow because the person detector ate the CPU; on the server it was fast (no detector effect seen) and ran
unpaced: **49 MB in 5 s (~10 MB/s)**, measured there by the owner. After the change the same route through the Vite proxy gave
1.83 MB in 5 s (0.37 MB/s). So: ~27x less data than the server's old figure, with a frame rate (10) that a person can follow. 0.36 MB/s is
still ~3 Mbit/s per viewer; halve it with `STREAM_FPS=5`, or shrink with `STREAM_MAX_SIDE=480` / `STREAM_JPEG_QUALITY=55`
(these variants were **not measured**).

| Detector speed while one viewer is watching (frames/s of the worker) | alone | with viewer | change |
|---|---|---|---|
| before (step 3 code), two runs | 3.25 / 16.5 (unpinned) | 2.0 / 10.25 | -38% / -38% |
| after, plain view, run 1 / run 2 | 3.0 / 2.5 | 2.75 / 1.75 | -8% / -30% |
| after, with overlay, run 1 / run 2 | 3.0 / 2.5 | 2.5 / 1.25 | -17% / -50% |
Read this with care: the laptop's "alone" speed moved by 30% between runs (2.5 to 3.25), far below the server's ~6.9 fps, and the
"after" run that was meant to be repeated 3 times in round-robin order (`tools/stream_bench_matrix.py --repeats 3`) was stopped by the
system for low memory and was not re-run. What the numbers do support: the viewer itself now costs ~15 % of a core instead of 160 - 350 %;
the plain view costs the worker less than before in both after-runs; the overlay costed the worker at least as much as the plain view in
both runs, so it stays off by default. Repeat on the server (see below) before turning it on.

Repeat on the server, in the backend container, with the worker busy on a camera:
```bash
docker compose exec backend python tools/stream_bench_matrix.py --clip /app/videos/<clip>.mp4 --cores 4 --repeats 3 --out /tmp/bench.json
# or one viewer only:   python tools/stream_bench.py viewer --clip /app/videos/<clip>.mp4 --seconds 20
```
(`--cores` pins on Windows only; on the server drop it and use `docker update --cpus` / the compose limits instead; the matrix script
runs the worker and the viewer as two processes.) The legacy rows need `git` and commit `497a519` in the checkout.

### `GET /api/cameras/test-videos`
Login required. Lists video files (`.mp4 .avi .mov .mkv .wmv .flv .webm`, regular files only) in `TEST_VIDEO_DIR`, natural order
(2 before 10), each as `{filename, url, description}`; `url` is the path inside the container, which is what the camera's `url` field
takes. `description` comes from an optional `clips.json` (`{"1.mp4": "text"}`) in that folder. Missing folder -> `[]`.
The friend's version had `/app/Test` fixed in the code; the default here is this repository's own `videos/` folder
(`./videos:/app/videos` in compose). Not ported: the friend's `normalize_video_url` (rewrites pasted Windows paths on camera create).

### Step 4: running the frontend on the laptop against the backend on the server (SSH tunnel)
One-time setup (Windows PowerShell; needs Node 18+ (`node -v`), git and the built-in `ssh`):
1. Get the code: `git clone --branch plan-a https://github.com/phoodis/Backend-Fall-Dectection.git` (or `git pull` in your checkout on `plan-a`), then `cd Backend-Fall-Dectection\frontend`.
2. `copy .env.example .env`. Leave `VITE_API_BASE_URL=/api` and `VITE_PROXY_TARGET=http://127.0.0.1:8932`. Optional Google sign-in: copy the
   seven `VITE_FIREBASE_*` lines from the old frontend's `.env` into this one (`.env` is not in git; do not paste them anywhere else).
3. `npm ci` (about 2 minutes; creates `node_modules`).

Every time:
4. Open the tunnel in its own PowerShell window and leave it open: `ssh -N -L 8932:127.0.0.1:8932 <user>@<server>`
   (if something on the laptop already uses port 8932, e.g. a local backend, use `-L 18932:127.0.0.1:8932` and set
   `VITE_PROXY_TARGET=http://127.0.0.1:18932` in `.env`).
5. Check the tunnel in another window: `curl http://127.0.0.1:8932/api/health` -> a JSON answer. No answer = the tunnel is not up
   (wrong user/host, or the backend container is down: `docker compose ps` on the server).
6. `npm run dev`, open the address it prints (`http://localhost:3000/`; if 3000 is taken Vite picks 3001 and prints that).
7. Check: log in; Camera management -> add a camera with "test video" from the dropdown (list comes from `TEST_VIDEO_DIR` on the server);
   Monitor -> the live view appears. In the browser's Network tab the stream request is `.../api/stream/camera/<id>?t=...` (a short token)
   and there is a `media-token` request before it; no request carries `token=` with a long login token.
8. Stop: Ctrl+C in the `npm run dev` window, then close the tunnel window.

Troubleshooting: `http proxy error ... ECONNREFUSED` in the Vite window = the tunnel is down or points to a different port;
live view shows the logo/error picture = the media token request failed (check the Network tab: 401 = logged out or `SECRET_KEY` changed on the server;
403 = the camera belongs to someone else); the live view stops after ~10 minutes and reconnects by itself (token life);
the Google button says it is not configured = no Firebase values in `.env` (username/password still works).
Server side for this step: put `STREAM_*` / `TEST_VIDEO_DIR` in the server's `.env` if the defaults are not wanted, keep a long random
`SECRET_KEY`, and recreate only the web container (`docker compose up -d --force-recreate backend`); the celery worker (detection) is unaffected
by every setting added in this step.

### Not verified in this step
The pages were not looked at in a browser: the browser tool timed out four times while the page loaded (the page printed no error
other than the expected "Firebase not configured" warning, and the dev server answered). Checked instead: `vite build` succeeds;
through the Vite proxy with a real backend: login, `GET /cameras/test-videos` (200, folder outside `/app`), media token (60 s, `overlay_available:false`),
the stream (200 multipart, 1.83 MB / 5 s), `?token=<login JWT>` (401), `/api/detector` and `/api/line/settings` (404, which the About and LINE pages now handle).
Please open the Monitor, About and notification-settings pages once yourself (step 7 above).
