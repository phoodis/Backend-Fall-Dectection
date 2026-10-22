<template>
  <div v-if="show" class="modal-overlay" @click.self="$emit('cancel')">
    <div class="modal-content">
      <div class="modal-header">
        <h3>แก้ไขกล้อง</h3>
        <button @click="$emit('cancel')" class="modal-close-btn">&times;</button>
      </div>
      <div class="modal-body">
        <form @submit.prevent="$emit('save')">

          <div class="form-group">
            <label for="edit-camera-name" class="form-label"
              >ชื่อกล้อง <span class="required">*</span></label
            >
            <input
              type="text"
              id="edit-camera-name"
              v-model="camera.name"
              class="form-input"
              placeholder="เช่น กล้องหน้าบ้าน, กล้องหลังบ้าน"
              autofocus
            />
          </div>

          <div class="form-group">
            <label for="edit-room-name" class="form-label">ชื่อห้อง/โซน</label>
            <input
              type="text"
              id="edit-room-name"
              v-model="camera.room_name"
              class="form-input"
              placeholder="เช่น ห้อง 101, โถงกลาง, ห้องผู้ป่วย 2"
            />
          </div>

          <div class="form-group">
            <label class="form-label">แหล่งวิดีโอ</label>
            <div class="source-type-toggle">
              <label>
                <input type="radio" value="url" v-model="sourceType" />
                กล้องจริง (RTSP/URL)
              </label>
              <label>
                <input type="radio" value="test" v-model="sourceType" />
                ไฟล์วิดีโอทดสอบ
              </label>
            </div>
          </div>

          <div class="form-group" v-if="sourceType === 'url'">
            <label for="edit-camera-url" class="form-label"
              >URL การเชื่อมต่อ <span class="required">*</span></label
            >
            <input
              type="text"
              id="edit-camera-url"
              v-model="camera.url"
              class="form-input"
              placeholder="เช่น rtsp://username:password@ip:port/path"
            />
            <small class="form-help">รองรับ RTSP, RTMP, HLS หรือ URL ของไฟล์วิดีโอ</small>
          </div>

          <div class="form-group" v-else>
            <label for="edit-camera-test-video" class="form-label"
              >เลือกไฟล์วิดีโอทดสอบ <span class="required">*</span></label
            >
            <select id="edit-camera-test-video" v-model="camera.url" class="form-input">
              <option value="" disabled>เลือกไฟล์วิดีโอ</option>
              <option v-for="v in testVideos" :key="v.filename" :value="v.url">
                {{ testVideoLabel(v) }}
              </option>
            </select>
            <small class="form-help" v-if="testVideos.length === 0">
              ไม่พบไฟล์วิดีโอทดสอบ — วางไฟล์ .mp4 ไว้ในโฟลเดอร์วิดีโอของ backend (ค่า TEST_VIDEO_DIR) แล้วเปิดฟอร์มนี้ใหม่
            </small>
            <small class="form-help" v-else>ไฟล์จากโฟลเดอร์วิดีโอของ backend</small>
          </div>

          <div class="form-group" v-if="showOwnerField">
            <label for="edit-owner-select" class="form-label"
              >เจ้าของกล้อง <span class="required">*</span></label
            >
            <select
              id="edit-owner-select"
              v-model="camera.owner_id"
              class="form-input"
              required
            >
              <option value="">เลือกเจ้าของกล้อง</option>
              <option v-for="user in users" :key="user.id" :value="user.id">
                {{ user.username }} ({{ user.role === 'admin' ? 'ผู้ดูแลระบบ' : 'ผู้ใช้ทั่วไป' }})
              </option>
            </select>
            <small class="form-help">เลือกผู้ใช้ที่จะเป็นเจ้าของกล้องนี้</small>
          </div>

          <div class="form-group">
            <label for="edit-detection-type" class="form-label">ประเภทการตรวจจับ</label>
            <select id="edit-detection-type" v-model="camera.detection_type" class="form-input">
              <option v-for="opt in DETECTION_TYPE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <small class="form-help">{{ DETECTION_TYPE_FORM_HELP }}</small>
          </div>

          <!-- See CameraManagementView: the v3 loop alerts at any hour, so the window is hidden for fall_v2. -->
          <div v-if="camera.detection_type === 'fall_v2'" class="form-group">
            <small class="form-help">แจ้งเตือนตลอด 24 ชั่วโมง: โหมดตรวจจับการล้ม (YOLO-pose) ไม่ใช้ช่วงเวลาแจ้งเตือน เพื่อไม่ให้การล้มนอกช่วงเวลาถูกกลืนหายไปโดยไม่มีใครรู้</small>
          </div>

          <div v-if="camera.detection_type !== 'fall_v2'" class="form-group">
            <label for="edit-alert-start-time" class="form-label">เวลาเริ่มการแจ้งเตือน (24 ชั่วโมง)</label>
            <input
              type="text"
              id="edit-alert-start-time"
              v-model="camera.alert_start_time"
              class="form-input"
              pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
              placeholder="เช่น 21:00"
              maxlength="5"
            />
            <small class="form-help">รูปแบบ: ชั่วโมง:นาที (00:00 - 23:59) เช่น 21:00 หรือ 09:00</small>
          </div>

          <div v-if="camera.detection_type !== 'fall_v2'" class="form-group">
            <label for="edit-alert-end-time" class="form-label">เวลาสิ้นสุดการแจ้งเตือน (24 ชั่วโมง)</label>
            <input
              type="text"
              id="edit-alert-end-time"
              v-model="camera.alert_end_time"
              class="form-input"
              pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
              placeholder="เช่น 05:00"
              maxlength="5"
            />
            <small class="form-help">รูปแบบ: ชั่วโมง:นาที (00:00 - 23:59) เช่น 05:00 หรือ 17:00</small>
          </div>

          <div class="form-group">
            <label for="edit-notification-cooldown" class="form-label">ระยะห่างการแจ้งเตือน (วินาที)</label>
            <input type="number" id="edit-notification-cooldown" v-model.number="camera.notification_cooldown_sec" class="form-input" min="1" step="1" />
            <small class="form-help">เวลาที่ต้องรอก่อนแจ้งเตือนครั้งต่อไป (ป้องกันการแจ้งเตือนซ้ำเร็วเกินไป) เช่น 30 วินาที, 60 วินาที (1 นาที), 600 วินาที (10 นาที)</small>
          </div>

          <!-- See CameraManagementView: the v3 detector ignores this field. -->
          <div class="form-group" :class="{ 'form-group-inactive': camera.detection_type === 'fall_v2' }">
            <label for="edit-ai-confidence-threshold" class="form-label">ความแม่นยำของ AI (0.0-1.0)</label>
            <input type="number" id="edit-ai-confidence-threshold" v-model.number="camera.ai_confidence_threshold" class="form-input" min="0" max="1" step="0.01"
              :disabled="camera.detection_type === 'fall_v2'" />
            <small class="form-help">ใช้กับโหมดตรวจจับรุ่นเก่าเท่านั้น โหมด "ตรวจจับการล้ม (เวอร์ชั่น 3)" ซึ่งเป็นโหมดที่แนะนำ ใช้ค่าที่ผ่านการวัดผลมาแล้ว (0.65) และไม่อ่านค่านี้</small>
          </div>

          <div class="form-actions">
            <button type="button" @click="$emit('cancel')" class="btn btn-secondary">ยกเลิก</button>
            <button type="submit" class="btn btn-primary">บันทึกการเปลี่ยนแปลง</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import cameraService from '@/services/cameraService'
import { DETECTION_TYPE_OPTIONS, DETECTION_TYPE_FORM_HELP } from '@/utils/detectionType'
import { testVideoLabel } from '@/utils/testVideos'

const props = defineProps({
  show: { type: Boolean, default: false },
  showOwnerField: { type: Boolean, default: false },
  users: { type: Array, default: () => [] },
})
defineEmits(['save', 'cancel'])

// The camera object being edited -- two-way bound with the parent's
// editingCamera ref (single source for what gets submitted; this
// component only owns the form UI, not the save/API logic, since that
// differs per page -- e.g. Monitor restarts detection on save, Camera
// Management redirects).
const camera = defineModel({ required: true })

const testVideos = ref([])
onMounted(async () => {
  try {
    testVideos.value = await cameraService.getTestVideos()
  } catch (error) {
    console.error('Failed to load test videos:', error)
  }
})

const sourceType = ref('url')
// Re-derive from the camera's actual url every time the modal opens for a
// (possibly different) camera, rather than leaving whatever was selected
// for the previous one.
watch(() => props.show, (isShown) => {
  if (isShown) {
    // a camera whose source is one of the server's test videos opens on the dropdown
    const url = camera.value.url || ''
    sourceType.value = testVideos.value.some((v) => v.url === url) ? 'test' : 'url'
  }
})
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  width: 90%;
  max-width: 560px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.25rem;
}

.modal-close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #6b7280;
  line-height: 1;
}

.modal-body {
  padding: 1.5rem;
}

.form-group {
  margin-bottom: 1.25rem;
}

.form-label {
  display: block;
  font-weight: 600;
  margin-bottom: 0.4rem;
}

.required {
  color: #dc2626;
}

.form-input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 1rem;
  box-sizing: border-box;
}

.form-group-inactive {
  opacity: 0.55;
}

.form-help {
  display: block;
  color: #6b7280;
  font-size: 0.8rem;
  margin-top: 0.25rem;
}

.source-type-toggle {
  display: flex;
  gap: 1.5rem;
  padding: 0.5rem 0;
}

.source-type-toggle label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: normal;
  cursor: pointer;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.btn {
  padding: 0.6rem 1.25rem;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  font-size: 0.95rem;
}

.btn-primary {
  background: #2563eb;
  color: white;
}

.btn-secondary {
  background: #e5e7eb;
  color: #111827;
}
</style>
