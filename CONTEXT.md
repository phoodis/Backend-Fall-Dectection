# CONTEXT.md — ระบบเฝ้าระวังผู้สูงอายุ (Elderly Surveillance System)

> ไฟล์นี้คือคู่มือทำความเข้าใจ + ลงมือทำ สำหรับโปรเจกต์ 2 repo:
> `Backend-Elderly-Surveillance` (Flask/Python) และ `FRONT_END_DETR_BED` (Vue 3/Vite)
> เขียนจากการอ่านโค้ดจริงในไฟล์ zip ที่ให้มา (สถานะ ณ 4 ส.ค. 2026)

---

## 0. TL;DR — อ่านตรงนี้ก่อนลงมือ

โปรเจกต์นี้ **รันตาม README ตรง ๆ ไม่ผ่าน** มี 3 เรื่องที่ต้องจัดการก่อน:

| # | ปัญหา | ผลกระทบ | ต้องทำอะไร |
|---|-------|---------|-----------|
| 1 | **ไฟล์โมเดล `.onnx` เป็น Git LFS pointer ไม่ใช่โมเดลจริง** | ระบบตรวจจับ **ทุกโหมด** ใช้ไม่ได้ (bed_exit, fall, fall_v2) | ดึงไฟล์จริงจาก Git LFS หรือขอจากเจ้าของโปรเจกต์ → §3.1 |
| 2 | **Frontend ต้องมี Firebase config ไม่งั้นเว็บขาวทั้งหน้า** | เปิดเว็บไม่ได้เลย | ใส่ค่า Firebase หรือแพตช์โค้ด 5 บรรทัด → §3.2 |
| 3 | **URL ต่าง ๆ hardcode ไว้สำหรับ Docker** (`http://backend:8932`, `/app/models/...`) | รันนอก Docker แล้วพัง / frontend ต่อ backend ไม่ติด | ตั้ง `.env` + แพตช์เล็กน้อย → §3.3, §3.4 |

**แผนที่ผมแนะนำ:** ทำ **Phase A** (รันบนโน้ตบุ๊กตัวเองด้วยไฟล์วิดีโอทดสอบ) ให้เห็นภาพก่อน แล้วค่อยทำ **Phase B** (ย้ายขึ้น VPS) — อย่ากระโดดขึ้น VPS ตั้งแต่แรก เพราะดีบักยากกว่ามาก

---

## 1. ระบบนี้คืออะไร

ระบบเฝ้าระวังผู้สูงอายุผ่านกล้องวงจรปิด ตรวจจับ 2 เหตุการณ์หลัก แล้วแจ้งเตือนผ่าน Telegram

**ความสามารถที่มีในโค้ด:**

- **Bed Exit Detection** — ตรวจจับการลุกออกจากเตียง (โมเดล MobileNetV2 แยกท่า `bed` / `sleep` / `sit`)
- **Fall Detection v1** (`fall`) — ตรวจจับการล้ม (โมเดล ONNX ตัวเก่า)
- **Fall Detection v2** (`fall_v2`) — ตรวจจับการล้มแบบ anomaly detection ด้วย **DeepSVDD** รวมฟีเจอร์ 3 ชนิด: RGB (ResNet50, 2048 มิติ) + Optical Flow (Farneback, 236 มิติ) + Pose (MediaPipe, 136 มิติ) และใช้ **YOLOv10x** นับจำนวนคน/ตรวจว่าอยู่คนเดียวหรือไม่
- **Camera Management** — เพิ่ม/ลบ/สั่ง start-stop กล้อง แต่ละกล้องตั้งเวลาแจ้งเตือนและ threshold ได้
- **Live Streaming** — ส่งภาพสดแบบ MJPEG (`multipart/x-mixed-replace`)
- **Telegram Alert** — แจ้งเตือนพร้อมภาพนิ่ง มี cooldown กันสแปม
- **Thai FRAT** — แบบประเมินความเสี่ยงล้มฉบับไทย (Thai Falls Risk Assessment Tool) แชร์ผลระหว่างผู้ใช้ได้
- **Auth** — JWT (access 1 ชม. / refresh 7 วัน) + blocklist สำหรับ logout, มี role `admin` / `user`

---

## 2. สถาปัตยกรรม

```
┌──────────────────────────────────────────────────────────────┐
│  เบราว์เซอร์ (โน้ตบุ๊กคุณ)                                      │
│  Vue 3 + Vite  :3000                                          │
│    ├─ เรียก REST API ตรง ๆ ที่ VITE_API_BASE_URL              │
│    └─ <img src=".../api/stream/camera/1"> รับภาพ MJPEG        │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP (CORS เปิดหมด origins:*)
┌───────────────────────────▼──────────────────────────────────┐
│  VPS ของคุณ — Docker Compose 6 services                       │
│                                                               │
│  ┌─────────────┐   ส่งงานผ่าน Redis    ┌──────────────────┐  │
│  │  backend    │ ───────────────────▶  │  celery_worker   │  │
│  │  Flask :8932│                       │  (ประมวลผล AI)   │  │
│  │  REST+MJPEG │ ◀──────────────────── │  YOLO+MediaPipe  │  │
│  └──────┬──────┘      เขียนผลลง DB      └────────┬─────────┘  │
│         │                                        │            │
│         │              ┌──────────┐              │            │
│         └─────────────▶│ postgres │◀─────────────┘            │
│                        │  :5432   │                           │
│                        └──────────┘                           │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐                │
│  │  redis   │  │ celery_beat  │  │  flower  │                │
│  │  :6379   │  │ (ลบ log เก่า)│  │  :5555   │                │
│  └──────────┘  └──────────────┘  └──────────┘                │
└───────────────────────────┬──────────────────────────────────┘
                            │ RTSP / ไฟล์วิดีโอ
                   ┌────────▼────────┐
                   │ กล้อง IP / .mp4 │
                   └─────────────────┘
```

**ทำไมต้องมี Celery?** เพราะการรัน AI ต่อกล้อง 1 ตัวคือลูปที่ไม่มีวันจบ (อ่านเฟรม → ประมวลผล → วนใหม่) ถ้ารันใน Flask จะบล็อก request อื่นทั้งหมด Celery จึงแยกไปเป็น background task — 1 กล้อง = 1 task ที่รันค้างไว้

**พอร์ตทั้งหมด:**

| Service | พอร์ต | หน้าที่ | ควรเปิดสู่อินเทอร์เน็ต? |
|---------|-------|---------|------------------------|
| backend (Flask) | 8932 | REST API + MJPEG stream | ✅ ใช่ |
| frontend (Vite) | 3000 | หน้าเว็บ | ✅ ใช่ |
| postgres | 5432 | ฐานข้อมูล | ❌ **ห้าม** (ดู §7.3) |
| redis | 6379 | คิวงาน Celery | ❌ **ห้าม** |
| flower | 5555 | หน้ามอนิเตอร์ Celery | ⚠️ ปิดหรือใส่รหัสผ่าน |

---

## 3. Blockers — ต้องแก้ก่อนถึงจะรันได้

### 3.1 ⛔ ไฟล์โมเดล ONNX เป็น Git LFS pointer (สำคัญที่สุด)

repo ตั้งค่า `.gitattributes` ว่า `*.onnx filter=lfs` แต่ตอนดาวน์โหลด zip จาก GitHub **ไฟล์ LFS จะไม่ถูกดึงมาด้วย** — ได้มาแค่ไฟล์ข้อความ 130 ไบต์ที่ชี้ไปยังไฟล์จริง

**เช็กเองได้:**

```bash
ls -la models/
# ถ้าไฟล์ .onnx มีขนาดแค่ ~130 bytes → ยังไม่ใช่ไฟล์จริง

head -1 models/deepsvdd_model.onnx
# ถ้าขึ้น "version https://git-lfs.github.com/spec/v1" → เป็น pointer
```

**สถานะจริงของไฟล์ในโฟลเดอร์ `models/`:**

| ไฟล์ | ขนาดที่ควรเป็น | ในไฟล์ zip ที่ให้มา | ใช้กับโหมด |
|------|---------------|---------------------|-----------|
| `bed_pose_mobilenetv2_3.onnx` | 8.88 MB | ❌ pointer 132 B | `bed_exit` |
| `fall_detection_model.onnx` | 186 KB | ❌ pointer 131 B | `fall` |
| `deepsvdd_model.onnx` | 5.62 MB | ❌ pointer 132 B | `fall_v2` |
| `yolov10x.pt` | 64.4 MB | ✅ ไฟล์จริง | `fall_v2` |
| `fall_detection_v2.pth` | 5.62 MB | ✅ ไฟล์จริง | (ไม่ถูกเรียกใช้) |
| `center.npy`, `*.json` | เล็ก | ✅ ไฟล์จริง | ทุกโหมด |

**วิธีแก้ — เลือกอย่างใดอย่างหนึ่ง:**

**ทางที่ 1 (แนะนำ) — clone ด้วย git lfs แทนการโหลด zip**

```bash
# ติดตั้ง git-lfs ก่อน
sudo apt install git-lfs        # Ubuntu
brew install git-lfs            # macOS
winget install GitHub.GitLFS    # Windows
git lfs install

git clone https://github.com/<เจ้าของ>/Backend-Elderly-Surveillance.git
cd Backend-Elderly-Surveillance
git lfs pull

ls -la models/   # ต้องเห็นไฟล์ขนาด MB แล้ว
```

**ทางที่ 2 — ขอไฟล์ `.onnx` โดยตรงจากคนที่ทำโปรเจกต์นี้** แล้ววางทับใน `models/`

**ทางที่ 3 (สำรอง, ต้องแก้โค้ด)** — ไฟล์ `fall_detection_v2.pth` เป็นไฟล์จริง และมีโค้ดเวอร์ชัน PyTorch อยู่ที่ `app/detection/v2_fall_detection.py` (บรรทัด 203 `torch.load(model_path)`) ซึ่งใช้ `.pth` ตัวนี้ได้ แต่ตอนนี้ `app/services/model_manager.py` เรียกเฉพาะเวอร์ชัน ONNX เท่านั้น ถ้าจำเป็นจริง ๆ ต้องเขียนโค้ดเชื่อมเพิ่ม — ทางนี้ได้แค่โหมด `fall_v2` เท่านั้น (bed_exit กับ fall ยังพังอยู่ดี)

> **ระหว่างที่ยังไม่มีไฟล์โมเดล:** ส่วนอื่นของระบบยังทดสอบได้หมด — login, จัดการผู้ใช้, เพิ่มกล้อง, ดูภาพสด MJPEG, Thai FRAT, Telegram แค่กด "เริ่มตรวจจับ" แล้วจะไม่มีผลลัพธ์ออกมา

---

### 3.2 ⛔ Frontend ต้องมี Firebase config ไม่งั้นเว็บขาวทั้งหน้า

ลำดับการโหลด: `main.js` → `stores/auth.js` → `services/firebaseAuthService.js` → `config/firebase.js` → เรียก `getAnalytics(app)` **ตั้งแต่ตอน import** ถ้าไม่มีค่า Firebase มันจะ throw ตั้งแต่บูต แอปจะไม่ mount และคุณจะเห็นแค่หน้าขาว

**วิธีแก้ ก) มี Firebase อยู่แล้ว / สร้างใหม่ได้** (แนะนำถ้าอยากใช้ปุ่ม "Login with Google")

1. เข้า [Firebase Console](https://console.firebase.google.com/) → สร้างโปรเจกต์
2. Authentication → Sign-in method → เปิด **Google**
3. Project settings → Your apps → Web app → คัดลอกค่า config
4. ใส่ในไฟล์ `.env` ของ frontend

**วิธีแก้ ข) ไม่อยากยุ่งกับ Firebase — แพตช์โค้ด**

แก้ไฟล์ `src/config/firebase.js` ตรงส่วนท้าย จากเดิม:

```js
let analytics = null
if (typeof window !== 'undefined') {
    analytics = getAnalytics(app)
}
```

เปลี่ยนเป็น:

```js
let analytics = null
if (typeof window !== 'undefined' && firebaseConfig.measurementId) {
    try {
        analytics = getAnalytics(app)
    } catch (e) {
        console.warn('[Firebase] ข้าม Analytics:', e.message)
    }
}
```

แค่นี้เว็บจะบูตได้ปกติ และยังล็อกอินด้วย username/password ผ่าน backend ได้ (ปุ่ม Google จะใช้ไม่ได้เท่านั้น)

---

### 3.3 ⚠️ Frontend ชี้ไป backend ผิดที่

มี 2 จุดที่ต้องดู:

**จุดที่ 1 — `VITE_API_BASE_URL` (ตัวจริงที่โค้ดใช้)**
`src/config/api.js` อ่านค่านี้ไปประกอบเป็น URL เต็ม เช่น `http://localhost:8932/api/auth/login` เรียกตรงไป backend เลย ไม่ผ่าน proxy (โชคดีที่ backend เปิด CORS ไว้ `origins: "*"` จึงเรียกข้ามโดเมนได้)

**จุดที่ 2 — Vite proxy ใน `vite.config.js`**
ตั้งไว้ `target: 'http://backend:8932'` — `backend` เป็นชื่อ service ใน Docker network ถ้ารัน `npm run dev` บนเครื่องปกติจะ resolve ไม่ได้ แก้เป็น:

```js
server: {
    proxy: {
        '/api': {
            target: 'http://localhost:8932',   // เดิม http://backend:8932
            changeOrigin: true,
            rewrite: (path) => path,
        },
    },
    ...
}
```

---

### 3.4 ⚠️ Path ที่ hardcode ไว้สำหรับ Docker เท่านั้น

| ไฟล์ | บรรทัด | ค่าที่ hardcode | ผลถ้ารันนอก Docker |
|------|--------|-----------------|---------------------|
| `app/services/model_manager.py` | ~63 | `/app/models/yolov10x.pt` | โหลด YOLO ไม่เจอ |
| `app/__init__.py` | ~52 | `/app/videos` | เสิร์ฟไฟล์วิดีโอไม่ได้ |
| `app/services/camera_manager.py` | หลายจุด | `/app/videos/`, `/app/tmp` | เปิดวิดีโอ/เซฟภาพแจ้งเตือนไม่ได้ |

**ข้อสรุป: ให้รัน backend ใน Docker เสมอ** จะเลี่ยงปัญหานี้ได้ทั้งหมด ไม่ต้องแก้โค้ดสักบรรทัด (นี่คือเหตุผลที่คู่มือนี้ใช้ Docker ทั้ง Phase A และ B)

---

### 3.5 ⚠️ โฟลเดอร์ `videos/` ไม่มีในโปรเจกต์

`docker-compose.yml` mount `./videos:/app/videos` ถ้าโฟลเดอร์นี้ไม่มี Docker จะสร้างให้เป็นโฟลเดอร์ว่างของ root ซึ่งอาจมีปัญหาสิทธิ์ — สร้างเองไว้ก่อนดีกว่า:

```bash
mkdir -p videos tmp
```

---

## 4. สเปกเครื่องที่ต้องใช้

### 4.1 เช็ก GPU บน VPS ก่อน

```bash
nvidia-smi                    # มี GPU + driver จะขึ้นตาราง
lspci | grep -i nvidia        # เห็นการ์ดจริงไหม
free -h && nproc && df -h     # RAM / CPU / พื้นที่ว่าง
```

ถ้า `nvidia-smi: command not found` และ `lspci` ไม่เจออะไร → **CPU อย่างเดียว** (VPS ทั่วไปเกือบทั้งหมดเป็นแบบนี้)

### 4.2 CPU-only ทำงานได้ไหม?

ได้ แต่ต้องเข้าใจว่ามันหนักแค่ไหน — โหมด `fall_v2` ต่อ 1 เฟรมต้องรัน:

1. YOLOv10x (ตัวใหญ่ที่สุดใน family YOLOv10) — นับคน
2. MediaPipe Pose — หา keypoint
3. Optical Flow Farneback — คำนวณการเคลื่อนไหว
4. ResNet50 — ดึงฟีเจอร์ RGB 2048 มิติ
5. DeepSVDD — ตัดสินว่าผิดปกติไหม

บน CPU ประมาณ **1–3 วินาที/เฟรม** ต่อกล้อง 1 ตัว

> ⚠️ **ข้อสังเกตสำคัญ:** `docker-compose.yml` ตั้ง `CUDA_VISIBLE_DEVICES=""` ไว้ที่ celery_worker อยู่แล้ว = **บังคับใช้ CPU** แม้จะมี GPU ก็ตาม ถ้าเครื่องคุณมี GPU และอยากใช้ ต้องลบบรรทัดนี้ออก + ติดตั้ง NVIDIA Container Toolkit + เปลี่ยน `onnxruntime` เป็น `onnxruntime-gpu` ใน `requirements.txt`

### 4.3 สเปกขั้นต่ำที่แนะนำ

| ทรัพยากร | ขั้นต่ำ | สบาย ๆ | หมายเหตุ |
|----------|---------|--------|----------|
| RAM | 8 GB | 16 GB | torch + ultralytics + mediapipe กินเยอะ, 1 worker ≈ 2–3 GB |
| vCPU | 4 | 8 | `CAMERA_MAX_PARALLEL` ไม่ควรเกินจำนวน vCPU |
| Disk | 20 GB | 40 GB | Docker image ตัวเดียว ≈ 6–8 GB (torch อย่างเดียว ~2.5 GB) |
| Python | 3.10 | 3.10 | `torch==2.0.1` ไม่มี wheel สำหรับ 3.12+ — Dockerfile ใช้ 3.10 อยู่แล้ว อย่าเปลี่ยน |

**ถ้า RAM 2–4 GB:** จะ build image ไม่ผ่านหรือ worker โดน OOM kill — ต้องเพิ่ม swap อย่างน้อย 4 GB

---

## 5. เส้นทางที่แนะนำ

```
Phase A — บนโน้ตบุ๊กคุณ (1–2 ชม.)          Phase B — บน VPS (1–2 ชม.)
├─ Docker Desktop + Node.js                ├─ ติดตั้ง Docker บน Ubuntu
├─ รัน backend ด้วย docker compose          ├─ ปิดพอร์ต DB/Redis, ตั้งรหัสผ่านใหม่
├─ รัน frontend ด้วย npm run dev            ├─ deploy backend
├─ ทดสอบด้วยไฟล์ .mp4                      ├─ ตั้ง Nginx + HTTPS (ถ้ามีโดเมน)
└─ เข้าใจระบบ ✔                            └─ ชี้ frontend มาที่ VPS ✔
```

---

## 6. Phase A — รันบนเครื่องตัวเอง (VS Code)

### 6.1 สิ่งที่ต้องติดตั้งก่อน

| โปรแกรม | เวอร์ชัน | ตรวจสอบด้วย |
|---------|---------|-------------|
| Docker Desktop | ล่าสุด | `docker --version` และ `docker compose version` |
| Node.js | 18 หรือ 20 LTS | `node -v` |
| Git + Git LFS | ล่าสุด | `git lfs version` |
| VS Code | ล่าสุด | — |

**VS Code extensions ที่ควรลง:**

```
Vue.volar                      ← Vue 3 (สำคัญ)
ms-python.python               ← Python
ms-azuretools.vscode-docker    ← จัดการ container
dbaeumer.vscode-eslint
esbenp.prettier-vscode
EditorConfig.EditorConfig
```

### 6.2 จัดโครงสร้างโฟลเดอร์

```
elderly-surveillance/
├── backend/          ← แตกจาก Backend-Elderly-Surveillance-main.zip
│   ├── models/       ← ต้องมีไฟล์ .onnx จริง (§3.1)
│   ├── videos/       ← สร้างเอง — วางไฟล์ .mp4 ทดสอบที่นี่
│   ├── tmp/          ← สร้างเอง — ภาพแจ้งเตือนจะถูกเซฟที่นี่
│   └── .env          ← สร้างเอง
└── frontend/         ← แตกจาก FRONT_END_DETR_BED-main.zip
    └── .env          ← สร้างเอง
```

**เปิดใน VS Code:** `File → Open Folder` เลือก `elderly-surveillance/` (โฟลเดอร์แม่ ไม่ใช่แยกทีละอัน) จะได้เห็นทั้งสองฝั่งพร้อมกันใน Explorer

### 6.3 ตั้งค่า backend `.env`

สร้างไฟล์ `backend/.env` — ใช้ไฟล์ `backend.env.template` ที่แนบมาได้เลย (คัดลอกแล้วเปลี่ยนชื่อเป็น `.env`)

```bash
cd backend
mkdir -p videos tmp
# คัดลอกเนื้อหาจาก backend.env.template มาใส่ .env
```

**ค่าที่ต้องเข้าใจ:**

| ตัวแปร | ค่าสำหรับ Phase A | ความหมาย |
|--------|-------------------|----------|
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/postgres` | `db` คือชื่อ service ใน compose — **อย่าเปลี่ยนเป็น localhost** |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | เช่นเดียวกัน `redis` คือชื่อ service |
| `PORT` | `8932` | ต้องตรงกับ port mapping ใน compose |
| `DEBUG` | `True` | Phase A ใช้ True ได้ / Phase B ต้อง `False` |
| `CAMERA_MAX_PARALLEL` | `2` | จำนวนกล้องที่ประมวลผลพร้อมกัน — เริ่มที่ 1–2 ก่อน |
| `ALERT_START_TIME` / `END` | `00:00` / `23:59` | ช่วงเวลาที่ยอมให้แจ้งเตือน — ตอนทดสอบเปิดทั้งวัน |
| `NOTIFICATION_COOLDOWN` | `60` | วินาที กันแจ้งเตือนซ้ำ — ตอนทดสอบตั้งสั้น ๆ |
| `ALERT_IMAGE_DIR` | `/app/tmp` | path **ในคอนเทนเนอร์** ไม่ใช่บนเครื่อง |

### 6.4 สตาร์ท backend

```bash
cd backend
docker compose up -d --build
```

รอบแรกจะนาน **10–25 นาที** (ดาวน์โหลด torch ~2.5 GB) ระหว่างรอดู log ได้:

```bash
docker compose logs -f backend
```

**สัญญาณว่าสำเร็จ** — จะเห็นข้อความประมาณนี้:

```
Created admin user: username='admin', password='admin123', role='admin'
Created test user: username='testuser', password='user123', role='user'
Database tables created successfully!
 * Running on http://0.0.0.0:8932
```

**ทดสอบ:**

```bash
curl http://localhost:8932/api/health
# ควรได้: {"message":"The server is running and operational.","status":"healthy"}

curl -X POST http://localhost:8932/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# ควรได้ access_token กลับมา
```

เช็กว่าครบ 6 container:

```bash
docker compose ps
# ต้องเห็น: db, backend, celery_worker, celery_beat, redis, flower — ทั้งหมด Up
```

### 6.5 ตั้งค่าและสตาร์ท frontend

```bash
cd ../frontend
npm install
```

สร้าง `frontend/.env` (ใช้ `frontend.env.template` ที่แนบมา):

```env
VITE_API_BASE_URL=http://localhost:8932/api
VITE_APP_NAME=V89 Elderly Surveillance
```

แก้ 2 จุดตาม §3.2 (firebase.js) และ §3.3 (vite.config.js) แล้วรัน:

```bash
npm run dev
```

เปิด `http://localhost:3000` → ล็อกอินด้วย `admin` / `admin123`

### 6.6 ทดสอบด้วยไฟล์วิดีโอ

1. หาไฟล์ `.mp4` (คลิปคนล้ม/คนลุกจากเตียง) วางใน `backend/videos/` เช่น `test_fall.mp4`
2. ในเว็บ → หน้า **จัดการกล้อง** → เพิ่มกล้องใหม่
   - **URL**: `/app/videos/test_fall.mp4` ← path ในคอนเทนเนอร์
   - **detection_type**: `fall_v2` (หรือ `bed_exit` / `fall`)
3. กด **เริ่มตรวจจับ** แล้วดู log:

```bash
docker compose logs -f celery_worker
```

จะเห็น `[Model Manager] Loading V2 ONNX Fall Detector...` (รอบแรกช้า เพราะ torchvision ต้องดาวน์โหลด weight ของ ResNet50 ≈ 100 MB จากอินเทอร์เน็ต)

4. หน้า **Monitor** จะแสดงภาพสด MJPEG

> **โค้ดรู้จัก URL 3 แบบ:** `rtsp://...` / `rtmp://...` = สตรีม, `/app/videos/xxx.mp4` = ไฟล์, `http://localhost:3000/videos/xxx.mp4` = จะถูกแปลงเป็น `/app/videos/xxx.mp4` อัตโนมัติ

---

## 7. Phase B — Deploy บน VPS Ubuntu

### 7.1 เตรียมเครื่อง

```bash
ssh user@<vps-ip>

sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg git git-lfs
git lfs install

# ติดตั้ง Docker (official)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# ออกแล้ว ssh เข้าใหม่ เพื่อให้ group มีผล

docker --version && docker compose version
```

**ถ้า RAM น้อยกว่า 8 GB เพิ่ม swap ก่อน:**

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

### 7.2 นำโค้ดขึ้น VPS

```bash
mkdir -p ~/apps && cd ~/apps
git clone <backend-repo-url> backend
cd backend && git lfs pull      # ← สำคัญมาก ดู §3.1
ls -la models/                  # ยืนยันว่าไฟล์ .onnx ขนาดเป็น MB
mkdir -p videos tmp
```

หรือถ้าใช้ zip: `scp` ขึ้นไปแล้ว unzip — แต่ **ต้องหาไฟล์ `.onnx` จริงมาวางเองต่างหาก**

### 7.3 🔒 แก้ความปลอดภัยก่อนเปิดใช้จริง (ห้ามข้าม)

`docker-compose.yml` ตอนนี้เปิด **Postgres 5432 และ Redis 6379 สู่อินเทอร์เน็ตแบบไม่มีรหัสผ่าน** ถ้า deploy ตามนี้ ฐานข้อมูลคุณจะถูกยึดภายในไม่กี่ชั่วโมง

**แก้ 4 อย่าง:**

**ก) ปิดพอร์ต DB/Redis** — สร้างไฟล์ `docker-compose.override.yml` (แนบมาให้แล้ว) ไว้ข้าง ๆ `docker-compose.yml` Docker Compose จะอ่านรวมอัตโนมัติ ไม่ต้องแก้ไฟล์เดิม

**ข) เปลี่ยนรหัสผ่านฐานข้อมูล** — ทั้งใน override และใน `DATABASE_URL`

**ค) สร้าง secret key ใหม่**

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"
```

**ง) `DEBUG=False`** ใน `.env`

**จ) เปลี่ยนรหัส admin ทันทีหลังล็อกอินครั้งแรก** — โค้ดสร้าง `admin/admin123` และ `testuser/user123` อัตโนมัติทุกครั้งที่บูต

### 7.4 Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8932/tcp      # backend API
sudo ufw allow 80,443/tcp    # ถ้าจะใช้ Nginx + HTTPS
sudo ufw enable
sudo ufw status numbered
```

**อย่า** เปิด 5432, 6379, 5555

### 7.5 สตาร์ท

```bash
cd ~/apps/backend
docker compose up -d --build
docker compose ps
curl http://localhost:8932/api/health
```

ทดสอบจากเครื่องคุณ: `curl http://<vps-ip>:8932/api/health`

### 7.6 ชี้ frontend มาที่ VPS

แก้ `frontend/.env`:

```env
VITE_API_BASE_URL=http://<vps-ip>:8932/api
```

แล้ว `npm run dev` บนโน้ตบุ๊กได้เลย — CORS เปิดไว้แล้ว

**ถ้าอยาก deploy frontend บน VPS ด้วย:**

```bash
npm run build          # ได้โฟลเดอร์ dist/
# เสิร์ฟ dist/ ด้วย Nginx หรือ npx serve
```

### 7.7 Nginx + HTTPS (จำเป็นถ้าจะใช้กล้องผ่านเบราว์เซอร์)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/surveillance`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8932/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # จำเป็นสำหรับ MJPEG stream — ห้าม buffer
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
        chunked_transfer_encoding off;
    }

    location / {
        root /var/www/surveillance;   # โฟลเดอร์ dist/ ของ frontend
        try_files $uri $uri/ /index.html;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/surveillance /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com
```

> `proxy_buffering off` สำคัญมาก — ถ้าไม่ปิด Nginx จะ buffer สตรีม MJPEG ไว้ ทำให้ภาพค้างไม่ขยับ

---

## 8. เรื่องกล้องโน้ตบุ๊ก

**ข้อจำกัดที่ต้องเข้าใจ:** โค้ดเรียก `cv2.VideoCapture(camera.url)` โดย `url` เป็น **string** เสมอ — ไม่รองรับ index กล้อง (`0`) แบบตรง ๆ และ VPS ไม่มีกล้องต่ออยู่ ดังนั้นจะใช้กล้องโน้ตบุ๊กต้องแปลงเป็นสตรีมก่อน

### วิธีที่ใช้ได้จริง: ทำโน้ตบุ๊กเป็น RTSP source

**1) เพิ่ม MediaMTX เข้า compose** — สร้าง `docker-compose.mediamtx.yml`:

```yaml
services:
  mediamtx:
    image: bluenviron/mediamtx:latest
    restart: always
    ports:
      - "8554:8554"
```

```bash
docker compose -f docker-compose.yml -f docker-compose.mediamtx.yml up -d
```

**2) ส่งภาพจากกล้องโน้ตบุ๊กด้วย FFmpeg**

Windows — หาชื่อกล้องก่อน:
```powershell
ffmpeg -list_devices true -f dshow -i dummy
```
แล้วส่ง:
```powershell
ffmpeg -f dshow -i video="Integrated Camera" -c:v libx264 -preset ultrafast -tune zerolatency -f rtsp rtsp://<vps-ip>:8554/webcam
```

macOS:
```bash
ffmpeg -f avfoundation -framerate 30 -i "0" -c:v libx264 -preset ultrafast -tune zerolatency -f rtsp rtsp://<vps-ip>:8554/webcam
```

Linux:
```bash
ffmpeg -f v4l2 -i /dev/video0 -c:v libx264 -preset ultrafast -tune zerolatency -f rtsp rtsp://<vps-ip>:8554/webcam
```

**3) เพิ่มกล้องในระบบ** ด้วย URL: `rtsp://mediamtx:8554/webcam` (ชื่อ service ใน Docker network)

**4) เปิด UDP/TCP 8554 บน firewall** และจำกัด IP ต้นทางถ้าทำได้:
```bash
sudo ufw allow from <ip-โน้ตบุ๊กคุณ> to any port 8554
```

> ถ้า Phase A รันทุกอย่างบนโน้ตบุ๊ก ใช้ `rtsp://host.docker.internal:8554/webcam` แทน (Docker Desktop บน Win/Mac)

**ทางเลือกอื่น:** ให้เบราว์เซอร์เปิดกล้องเองด้วย `getUserMedia()` แล้วส่งเฟรมไป backend — แต่โค้ดปัจจุบัน **ไม่รองรับ** ต้องเขียน endpoint รับเฟรมใหม่ทั้งหมด และต้องมี HTTPS ด้วย (เบราว์เซอร์บล็อกกล้องบน HTTP ที่ไม่ใช่ localhost)

---

## 9. Checklist ตรวจสอบว่าใช้งานได้

```
[ ] docker compose ps → เห็น 6 services สถานะ Up
[ ] curl /api/health → {"status":"healthy"}
[ ] login admin/admin123 → ได้ access_token
[ ] ls -la models/ → ไฟล์ .onnx ขนาดเป็น MB (ไม่ใช่ 130 bytes)
[ ] เปิด http://localhost:3000 → เห็นหน้าเว็บ (ไม่ใช่หน้าขาว)
[ ] ล็อกอินผ่านเว็บได้
[ ] เพิ่มกล้อง (video file) สำเร็จ
[ ] กด start → celery_worker log ขึ้น "Loading V2 ONNX Fall Detector"
[ ] หน้า Monitor เห็นภาพขยับ
[ ] มี record ใน /api/detection-logs
[ ] Telegram แจ้งเตือนเข้า (ถ้าตั้งค่าไว้)
```

---

## 10. Troubleshooting

| อาการ | สาเหตุที่เป็นไปได้ | วิธีแก้ |
|-------|--------------------|--------|
| `Error loading fall detector: ... is not a valid ONNX model` | ไฟล์เป็น LFS pointer | §3.1 |
| หน้าเว็บขาวเปล่า console ขึ้น Firebase error | ไม่มี Firebase config | §3.2 |
| `ERR_CONNECTION_REFUSED` ตอนล็อกอิน | `VITE_API_BASE_URL` ผิด / backend ไม่ขึ้น | เช็ก `curl /api/health` |
| `getaddrinfo failed: backend` | Vite proxy ชี้ Docker hostname | §3.3 |
| Container `celery_worker` restart วน | RAM ไม่พอ (OOM) | เพิ่ม swap §7.1 / ลด `CAMERA_MAX_PARALLEL` |
| `could not translate host name "db"` | รัน backend นอก Docker | รันใน Docker เท่านั้น §3.4 |
| build ค้างนาน / ล้มตอนติดตั้ง torch | เน็ตช้าหรือ disk เต็ม | `df -h`, `docker system prune -a` |
| ภาพสตรีมค้างไม่ขยับ (ผ่าน Nginx) | Nginx buffer สตรีมไว้ | ใส่ `proxy_buffering off` §7.7 |
| กล้องเปิดไม่ได้ ไม่มี error ชัดเจน | path/URL ผิด | ต้องเป็น `/app/videos/xxx.mp4` (path ในคอนเทนเนอร์) |
| ตรวจจับช้ามาก (หลายวินาที/เฟรม) | CPU-only + YOLOv10x | ปกติ — ลดจำนวนกล้อง หรือเปลี่ยนเป็น YOLOv10n/s |
| Telegram ไม่เข้า | นอกช่วง `ALERT_START/END_TIME` หรือติด cooldown | ตั้ง `00:00`–`23:59`, cooldown `60` |
| เวลาใน log เพี้ยน | ทุก service ตั้ง `TZ=Asia/Bangkok` แล้ว | ถ้ายังเพี้ยน เช็ก timezone ของ VPS |

**คำสั่งดีบักที่ใช้บ่อย:**

```bash
docker compose logs -f backend          # log API
docker compose logs -f celery_worker    # log การประมวลผล AI (ดูตัวนี้บ่อยสุด)
docker compose exec backend bash        # เข้าไปในคอนเทนเนอร์
docker compose exec backend ls -la /app/models/   # เช็กไฟล์โมเดลในคอนเทนเนอร์
docker stats                            # ดู RAM/CPU แบบ realtime
docker compose restart celery_worker
docker compose down                     # หยุด (ข้อมูล DB ยังอยู่ใน volume)
docker compose down -v                  # หยุด + ลบข้อมูล DB ทั้งหมด ⚠️
```

---

## 11. แผนที่ไฟล์สำคัญ

### Backend

```
app/
├── __init__.py                    ← create_app(), init DB, สร้าง user admin อัตโนมัติ, CORS
├── config.py                      ← อ่านค่าทั้งหมดจาก .env มารวมที่นี่
├── routes/                        ← REST endpoints (Blueprint)
│   ├── auth.py                    ← login/logout/refresh (JWT)
│   ├── cameras.py                 ← CRUD กล้อง + start/stop detection
│   ├── stream.py                  ← MJPEG streaming
│   ├── admin.py, logs.py, telegram.py, thai_frat.py, alerts.py, health.py
├── services/
│   ├── camera_manager.py  (35 KB) ← ⭐ หัวใจของระบบ — Celery tasks ลูปอ่านเฟรม+เรียก detector
│   ├── model_manager.py           ← Singleton โหลดโมเดลครั้งเดียว (lazy load)
│   ├── stream_service.py          ← generator ผลิตเฟรม MJPEG
│   ├── alert_service.py           ← ตัดสินใจว่าจะแจ้งเตือนไหม (เวลา + cooldown)
│   └── telegram_service.py        ← ส่งข้อความ/รูปเข้า Telegram
├── detection/
│   ├── bed_exit.py                ← ตรวจการลุกจากเตียง (MobileNetV2 ONNX)
│   ├── fall_detection.py          ← ตรวจการล้ม v1
│   ├── v2_fall_detection_onnx.py  ← ⭐ ตัวที่ระบบใช้จริง (DeepSVDD ONNX + YOLO + MediaPipe)
│   └── v2_fall_detection.py       ← เวอร์ชัน PyTorch (ไม่ได้ถูกเรียกใช้ — ดู §3.1 ทางที่ 3)
└── models/                        ← ตาราง SQLAlchemy (user, camera, detection_log, ...)

API_DOCUMENTATION.md               ← ⭐ รายละเอียด endpoint ทั้งหมด อ่านตัวนี้ก่อนแก้ frontend
docker-compose.yml                 ← นิยาม 6 services
Dockerfile                         ← Python 3.10-slim + lib สำหรับ OpenCV
```

### Frontend

```
src/
├── main.js                        ← entry point
├── config/
│   ├── api.js                     ← ⭐ รวม endpoint ทั้งหมด + getApiBaseUrl()
│   └── firebase.js                ← ⚠️ จุดที่ทำให้เว็บขาว (§3.2)
├── services/                      ← ชั้นเรียก API (api.js, authService.js, cameraService.js, ...)
├── stores/                        ← Pinia state (auth, backend)
├── router/index.js                ← เส้นทาง + guard (requiresAuth / requiresAdmin)
└── views/
    ├── StartView.vue              ← หน้า login
    ├── DashboardView.vue
    ├── CameraManagementView.vue   ← เพิ่ม/แก้กล้อง (admin only)
    ├── MonitorView.vue            ← ⭐ ดูภาพสด
    ├── UserManagementView.vue     ← จัดการผู้ใช้ (admin only)
    ├── NotificationSettingsView.vue
    └── ThaiFrat*.vue              ← แบบประเมิน Thai FRAT
vite.config.js                     ← ⚠️ proxy ต้องแก้ (§3.3)
```

---

## 12. ค่าตั้งต้นและข้อมูลอ้างอิง

| รายการ | ค่า |
|--------|-----|
| Admin | `admin` / `admin123` — **เปลี่ยนทันทีบน production** |
| Test user | `testuser` / `user123` |
| API base | `http://<host>:8932/api` |
| Flower | `http://<host>:5555` |
| Frontend dev | `http://localhost:3000` |
| `detection_type` ที่รองรับ | `bed_exit`, `fall`, `fall_v2` |
| Access token อายุ | 1 ชั่วโมง |
| Refresh token อายุ | 7 วัน |
| Timezone | `Asia/Bangkok` (ตั้งไว้ทุก service) |
| ลบ log เก่าอัตโนมัติ | ทุกวัน 02:00 (เก็บย้อนหลัง `LOG_RETENTION_DAYS` วัน) |

---

## 13. สิ่งที่ควรตัดสินใจ/ตรวจสอบเพิ่ม

1. **ไฟล์โมเดล `.onnx` จริงอยู่ที่ไหน** — เรื่องนี้ต้องเคลียร์ก่อนอย่างอื่นทั้งหมด ถ้าหาไม่ได้ ระบบตรวจจับใช้ไม่ได้เลย
2. **สเปก VPS จริง** — RAM/vCPU/disk ถ้าต่ำกว่า 8 GB / 4 vCPU ต้องวางแผนเพิ่ม swap หรือลดขนาดโมเดล
3. **มีโดเมนไหม** — ถ้าไม่มี จะใช้ HTTPS ไม่ได้ ซึ่งจำกัดทางเลือกเรื่องกล้องผ่านเบราว์เซอร์
4. **Firebase** — ถ้าไม่ต้องการ Google login ให้แพตช์ตาม §3.2 จะเร็วกว่าสร้างโปรเจกต์ใหม่
5. **beat schedule ไม่ทำงาน** — `celery_worker.py` นิยาม `beat_schedule` ไว้ แต่ `docker-compose.yml` สั่ง `celery -A app.celery beat` ซึ่งไม่ได้ import ไฟล์นั้น ผลคือ task ลบ log เก่าจะไม่ทำงาน (ไม่ใช่ blocker แต่ควรรู้ไว้)
