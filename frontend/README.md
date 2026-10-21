# V89 Elderly Surveillance

ระบบตรวจจับความเคลื่อนไหวและแจ้งเตือนอัจฉริยะ

## การติดตั้ง

### การติดตั้งแบบปกติ

```bash
# ติดตั้ง dependencies
npm install

# รัน development server
npm run dev

# build สำหรับ production
npm run build
```

This frontend is not part of `docker-compose.yml`: run it with `npm run dev` on your computer
(steps for a backend on a server, through an SSH tunnel, are in `docs/migration_plan_A.md`, section
"Step 4: running the frontend"). The `docker build`/`docker run` commands below make a standalone
container for just this frontend (set `VITE_PROXY_TARGET=http://backend:8932` for it) but are not
required or tested as part of the normal setup.

```bash
# build Docker image
docker build -t frontend .

# รัน container (แบบเชื่อมต่อกับ backend network)
docker run -d -p 3000:3000 --network backend-elderly-surveillance-main_default --name frontend-app frontend

# หรือรันแบบ standalone
docker run -d -p 3000:3000 --name frontend-app frontend
```

## การตั้งค่า Firebase (ไม่บังคับ)

Firebase มีไว้เฉพาะปุ่ม "เข้าสู่ระบบด้วย Google" และ analytics เท่านั้น -- ไม่มีค่านี้ก็เข้าใช้งานได้ปกติด้วย
username/password (ดูด้านล่าง)

1. สร้างโปรเจค Firebase ที่ [Firebase Console](https://console.firebase.google.com/)
2. เปิดใช้งาน Authentication และเพิ่ม Google เป็น Sign-in method
3. คัดลอกค่า configuration จาก Project settings และนำมาใส่ในไฟล์ `.env` (ดูตัวอย่างใน `.env.example`)

## เทคโนโลยีที่ใช้
- Vue 3
- Vite
- Firebase Authentication (ไม่บังคับ)
- Pinia
- Vue Router

## การแก้ไขปัญหา

### ถ้าเจอปัญหา PowerShell execution policy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### ถ้าเจอปัญหา dependency:
```bash
# ลบทุกอย่างและติดตั้งใหม่
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
```

## คุณสมบัติ

- ✅ การเข้าสู่ระบบแบบปกติ (username/password)
- ✅ การเข้าสู่ระบบด้วย Google (Firebase)
- ✅ จัดการกล้องวงจรปิด
- ✅ ระบบมอนิเตอร์แบบเรียลไทม์
- ✅ การแจ้งเตือนอัตโนมัติ
- ✅ ระบบการตั้งค่าการแจ้งเตือน
- ✅ รองรับ AI Detection หลายรูปแบบ:
  - `bed_exit`: ตรวจจับการลุกจากเตียง
  - `fall`: ตรวจจับการล้ม (Enhanced Detection)
  - `fall_v2`: ตรวจจับการล้ม (เวอร์ชั่น 3 - YOLO-pose, โมเดลล่าสุด แนะนำให้ใช้)

## การใช้งาน

### ข้อมูลสำหรับทดสอบ
- **Username**: admin
- **Password**: admin123

หรือใช้การเข้าสู่ระบบด้วย Google

## เทคโนโลยีที่ใช้

- Vue 3 + Composition API
- Pinia (State Management)
- Vue Router
- Firebase Authentication
- Vite

## โครงสร้างโปรเจ็ค

```
src/
├── components/       # Vue components
├── views/           # หน้าต่างๆ ของแอป
├── stores/          # Pinia stores
├── services/        # API services
├── config/          # ไฟล์ config
└── router/          # Vue Router config
```

## การตั้งค่าสำหรับการพัฒนา

โปรเจคนี้ใช้ Vite, Vue 3 และ Pinia

### คำสั่งที่ใช้บ่อย

```bash
# เริ่มเซิร์ฟเวอร์สำหรับพัฒนา
npm run dev

# สร้างไฟล์สำหรับ production
npm run build

# ตรวจสอบโค้ดด้วย ESLint
npm run lint

# จัดรูปแบบโค้ดด้วย Prettier
npm run format
```

### คำสั่ง Docker

```bash
# build image ใหม่
docker build -t frontend .

# รัน container
docker run -d -p 3000:3000 --network backend-elderly-surveillance-main_default --name frontend-app frontend

# ดู logs
docker logs frontend-app

# หยุด container
docker stop frontend-app

# ลบ container
docker rm frontend-app

# เข้าใน container เพื่อ debug
docker exec -it frontend-app sh
```

## สถาปัตยกรรม

Frontend: Vue 3 + Pinia + Vue Router
Backend: Flask + Celery + PostgreSQL + Redis -- อยู่ใน repo เดียวกันนี้เอง (`../` จาก
โฟลเดอร์นี้) วิธีรันทั้งระบบดู [README.md ที่ root](../README.md)

## การเชื่อมต่อกับ Backend

เชื่อมต่อกับ Backend API ที่กำหนด endpoint ตามที่ระบุใน `src/config/api.js`

- `VITE_API_BASE_URL=/api` (ค่าแนะนำ) เบราว์เซอร์เรียก `localhost:3000/api` แล้ว Vite ส่งต่อไปที่
  `VITE_PROXY_TARGET` (ค่าเริ่มต้น `http://127.0.0.1:8932` ใช้ได้ทั้งบนเครื่องเดียวกับ backend และผ่าน SSH tunnel;
  ใน Docker ตั้งเป็น `http://backend:8932`)
- หรือใส่ URL เต็มเช่น `http://127.0.0.1:8932/api` ให้เบราว์เซอร์เรียก backend ตรง ๆ
- ไฟล์ `.env` ไม่ถูกเก็บใน git; ค่า Firebase จริงใส่ที่นั่นเท่านั้น (ดู `.env.example`)

## ลิขสิทธิ์

© 2023 V89 Elderly Surveillance - สงวนลิขสิทธิ์
