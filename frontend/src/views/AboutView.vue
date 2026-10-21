<template>
  <div class="about">
    <div class="about-content card">
      <h1 class="page-title">เกี่ยวกับ V89 Fall Management System</h1>

      <div class="about-section">
        <h2>ระบบตรวจจับความเคลื่อนไหวและแจ้งเตือนอัจฉริยะ</h2>
        <p>
          V89 Fall Management System เป็นระบบตรวจจับความเคลื่อนไหวผ่านกล้องวงจรปิด พร้อมระบบแจ้งเตือนอัตโนมัติ
          ออกแบบมาเพื่อเพิ่มความปลอดภัยให้กับบ้าน สำนักงาน หรืออาคารสถานที่ต่างๆ
        </p>
      </div>

      <div class="about-section">
        <h2>คุณสมบัติหลัก</h2>
        <ul class="feature-list">
          <li>รองรับการเชื่อมต่อกล้องวงจรปิดหลายรูปแบบ (RTSP, RTMP, HLS)</li>
          <li>ระบบตรวจจับความเคลื่อนไหวอัตโนมัติ</li>
          <li>การแจ้งเตือนแบบเรียลไทม์</li>
          <li>การตั้งค่าช่วงเวลาการแจ้งเตือน</li>
          <li>จัดเก็บบันทึกกิจกรรมและการแจ้งเตือน</li>
          <li>หน้า Dashboard สำหรับมอนิเตอร์</li>
        </ul>
      </div>

      <div class="about-section">
        <h2>เวอร์ชั่น</h2>
        <p>V89 Fall Management System เวอร์ชั่น 1.0.0</p>
        <p>พัฒนาโดยทีม V89</p>
      </div>
    </div>
  </div>
</template>


<style scoped>
.section-note { font-size: 0.85rem; color: #666; margin: 0.35rem 0 0.75rem; }
.detector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 0.4rem 1.25rem;
}
.detector-item {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid #eee;
}
.detector-item span { color: #555; }
.detector-item b { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85rem; }
.detector-measured {
  margin-top: 0.9rem;
  padding: 0.6rem 0.75rem;
  border-radius: 6px;
  font-size: 0.9rem;
  line-height: 1.55;
}
.detector-measured.ok { background: #eef7ee; border-left: 4px solid #2e7d32; }
/* Deliberately loud: an unmeasured combination means no published accuracy figure describes
   what is running, and that is worth interrupting someone over. */
.detector-measured.warn { background: #fdecea; border-left: 4px solid #c62828; }
.detector-warn { color: #c62828; }
.profile-saved {
  background: #eef7ee;
  border-left: 4px solid #2e7d32;
  padding: 0.6rem 0.75rem;
  border-radius: 6px;
  font-size: 0.9rem;
  line-height: 1.55;
}
.profile-list { display: flex; flex-direction: column; gap: 0.5rem; margin: 0.75rem 0; }
.profile-row {
  display: flex;
  gap: 0.7rem;
  align-items: flex-start;
  padding: 0.7rem 0.8rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  cursor: pointer;
}
.profile-row:hover { border-color: #999; }
.profile-row.is-chosen { border-color: #1565c0; background: #f5f9ff; }
/* What is running is stated separately from what is selected: they are different facts and a
   page that merged them would hide an unsaved change. */
.profile-row.is-running { box-shadow: inset 3px 0 0 #2e7d32; }
.profile-body { display: flex; flex-direction: column; gap: 0.15rem; }
.profile-title { font-weight: 600; }
.profile-now {
  margin-left: 0.4rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: #2e7d32;
  border: 1px solid #2e7d32;
  border-radius: 999px;
  padding: 0.05rem 0.4rem;
}
.profile-measured { font-size: 0.85rem; color: #1565c0; font-weight: 600; }
.profile-note { font-size: 0.82rem; color: #555; line-height: 1.5; }
.btn-apply {
  padding: 0.55rem 1.1rem;
  border: none;
  border-radius: 6px;
  background: #1565c0;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}
.btn-apply:disabled { background: #b0bec5; cursor: default; }

.about {
  padding: 1rem;
}

.about-content {
  max-width: 800px;
  margin: 0 auto;
}

.about-section {
  margin-bottom: 2rem;
}

.about-section h2 {
  color: #1e40af;
  font-size: 1.5rem;
  margin-bottom: 1rem;
  font-weight: 600;
}

.about-section p {
  line-height: 1.6;
  color: #374151;
}

.feature-list {
  list-style-type: disc;
  padding-left: 2rem;
  color: #374151;
}

.feature-list li {
  margin-bottom: 0.5rem;
}

@media (min-width: 1024px) {
  .about {
    min-height: calc(100vh - 200px);
    display: flex;
    align-items: flex-start;
    padding: 2rem;
  }
}
</style>
