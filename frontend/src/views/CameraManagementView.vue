<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCameraStore } from '@/stores/camera'
import { useAuthStore } from '@/stores/auth'
import adminService from '@/services/adminService'
import cameraService from '@/services/cameraService'
import { getDetectionTypeText, DETECTION_TYPE_OPTIONS, DETECTION_TYPE_FORM_HELP } from '@/utils/detectionType'
import { testVideoLabel } from '@/utils/testVideos'
import CameraEditModal from '@/components/camera/CameraEditModal.vue'
import IconCamera from '@/components/icons/IconCamera.vue'
import SearchFilter from '@/components/common/SearchFilter.vue'

const cameraStore = useCameraStore()
const authStore = useAuthStore()
const router = useRouter()

// ตรวจสอบว่าเป็น admin หรือไม่
const isAdmin = computed(() => authStore.isAdmin)
const canManageCameras = computed(() => authStore.canManageCameras)

// ถ้าไม่ใช่ admin ให้ redirect ไป monitor
if (!canManageCameras.value) {
  router.push('/monitor')
}

const newCamera = ref({
  id: '',
  name: '',
  room_name: '',
  url: '',
  detection_type: 'fall_v2', // YOLO-pose, the model the system is built around (see DETECTION_TYPE_OPTIONS)
  owner_id: null, // เพิ่มเพื่อระบุเจ้าของกล้อง
  alert_start_time: '21:00',
  alert_end_time: '05:00',
  notification_cooldown_sec: 600, // วินาที
  ai_confidence_threshold: 0.5,
})

const users = ref([]) // รายการผู้ใช้สำหรับเลือกเจ้าของกล้อง
const testVideos = ref([]) // รายชื่อไฟล์วิดีโอทดสอบในโฟลเดอร์วิดีโอของ backend
const newCameraSourceType = ref('url') // 'url' = พิมพ์เอง, 'test' = เลือกจากไฟล์ทดสอบ (ใช้เฉพาะฟอร์ม "เพิ่มกล้อง" -- ฟอร์มแก้ไขอยู่ใน CameraEditModal.vue)
const message = ref('')
const messageType = ref('')
const searchQuery = ref('')

// เพิ่ม state สำหรับการแก้ไขกล้อง
const isEditing = ref(false)
const editingCamera = ref({
  id: '',
  name: '',
  room_name: '',
  url: '',
  detection_type: 'bed_exit',
  owner_id: null,
  alert_start_time: '21:00',
  alert_end_time: '05:00',
  notification_cooldown_sec: 600,
  ai_confidence_threshold: 0.5,
})
const showEditModal = ref(false)

// Computed properties
const allCameras = computed(() => cameraStore.cameras)
const cameras = computed(() => {
  if (!searchQuery.value) return allCameras.value

  return allCameras.value.filter(
    (camera) =>
      camera.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      camera.url.toLowerCase().includes(searchQuery.value.toLowerCase()),
  )
})

// Helper functions for state management
function saveCameraManagementState() {
  const state = {
    searchQuery: searchQuery.value
  }
  localStorage.setItem('cameraManagementState', JSON.stringify(state))
}

function loadCameraManagementState() {
  const savedState = localStorage.getItem('cameraManagementState')
  if (savedState) {
    try {
      const state = JSON.parse(savedState)
      searchQuery.value = state.searchQuery || ''
    } catch (e) {
      console.error('Error loading camera management state:', e)
    }
  }
}

// Watch for search query changes
watch(searchQuery, () => {
  saveCameraManagementState()
})

onMounted(async () => {
  // โหลดข้อมูลกล้อง
  if (allCameras.value.length === 0) {
    cameraStore.loadCameras()
  }

  // โหลดสถานะที่บันทึกไว้
  loadCameraManagementState()

  // โหลดรายการผู้ใช้สำหรับ admin
  if (isAdmin.value) {
    try {
      const response = await adminService.getUsers()
      users.value = response.users || []
    } catch (error) {
      console.error('Failed to load users:', error)
    }
  }

  // โหลดรายชื่อไฟล์วิดีโอทดสอบ (สำหรับ dropdown เลือกแหล่งวิดีโอ)
  try {
    testVideos.value = await cameraService.getTestVideos()
  } catch (error) {
    console.error('Failed to load test videos:', error)
  }
})

async function addCamera() {
  if (!newCamera.value.name || !newCamera.value.url) {
    message.value = 'กรุณากรอกชื่อกล้องและ URL ให้ครบถ้วน'
    messageType.value = 'danger'
    return
  }

  if (!newCamera.value.owner_id) {
    message.value = 'กรุณาเลือกเจ้าของกล้อง'
    messageType.value = 'danger'
    return
  }

  try {
    const camera = {
      name: newCamera.value.name,
      room_name: newCamera.value.room_name,
      url: newCamera.value.url,
      detection_type: newCamera.value.detection_type,
      owner_id: newCamera.value.owner_id,
      alert_start_time: newCamera.value.alert_start_time,
      alert_end_time: newCamera.value.alert_end_time,
      notification_cooldown: newCamera.value.notification_cooldown_sec,
      ai_confidence_threshold: newCamera.value.ai_confidence_threshold,
    }
    const result = await cameraStore.addCamera(camera)
    if (result) {
      message.value = `เพิ่มกล้อง ${camera.name} เรียบร้อยแล้ว`
      messageType.value = 'success'
      // Reset form
      newCamera.value = {
        id: '',
        name: '',
        room_name: '',
        url: '',
        detection_type: 'fall_v2',
        owner_id: null,
        alert_start_time: '21:00',
        alert_end_time: '05:00',
        notification_cooldown_sec: 600,
        ai_confidence_threshold: 0.5,
      }
      setTimeout(() => {
        router.push('/monitor')
      }, 1200)
    } else {
      message.value = 'เกิดข้อผิดพลาดในการเพิ่มกล้อง (ไม่พบข้อมูลกล้องที่เพิ่ม)'
      messageType.value = 'danger'
    }
  } catch (err) {
    message.value = 'เกิดข้อผิดพลาดในการเพิ่มกล้อง'
    messageType.value = 'danger'
  }
  setTimeout(() => {
    message.value = ''
  }, 3000)
}

function removeCamera(camera) {
  if (confirm(`ต้องการลบกล้อง ${camera.name} ใช่หรือไม่?`)) {
    cameraStore.removeCamera(camera)
    message.value = `ลบกล้อง ${camera.name} เรียบร้อยแล้ว`
    messageType.value = 'info'

    setTimeout(() => {
      message.value = ''
    }, 3000)
  }
}

// เพิ่มฟังก์ชันเริ่มแก้ไขกล้อง
function startEditCamera(camera) {
  // คัดลอกข้อมูลกล้องที่ต้องการแก้ไข
  editingCamera.value = {
    ...camera,
    owner_id: camera.owner?.id || camera.owner_id,
    notification_cooldown_sec: camera.notification_cooldown ?? 600,
    detection_type: camera.detection_type || 'bed_exit',
    alert_start_time: camera.alert_start_time || '21:00',
    alert_end_time: camera.alert_end_time || '05:00',
    ai_confidence_threshold: camera.ai_confidence_threshold ?? 0.5,
  }
  isEditing.value = true
  showEditModal.value = true
}

// ฟังก์ชันบันทึกการแก้ไขกล้อง
async function saveEditCamera() {
  if (!editingCamera.value.name || !editingCamera.value.url) {
    message.value = 'กรุณากรอกชื่อกล้องและ URL ให้ครบถ้วน'
    messageType.value = 'danger'
    return
  }

  try {
    const updateData = {
      name: editingCamera.value.name,           // ← explicit fields
      url: editingCamera.value.url,             // ← ไม่ใช้ spread
      room_name: editingCamera.value.room_name,
      detection_type: editingCamera.value.detection_type,
      alert_start_time: editingCamera.value.alert_start_time,
      alert_end_time: editingCamera.value.alert_end_time,
      notification_cooldown: editingCamera.value.notification_cooldown_sec,
      ai_confidence_threshold: editingCamera.value.ai_confidence_threshold,
    }

    await cameraStore.updateCamera(editingCamera.value.id, updateData)

    // ปิด modal ก่อน reload เพื่อไม่ให้ MediaViewer render ด้วยข้อมูลเก่า
    showEditModal.value = false
    isEditing.value = false

    // รอ loadCameras เสร็จก่อน
    await cameraStore.loadCameras()

    // ตรวจสอบว่า cameras โหลดมาครบและไม่มี undefined
    const validCameras = cameras.value.filter(c => c.id && c.url)
    if (validCameras.length !== cameras.value.length) {
      console.warn('Some cameras have undefined fields:', cameras.value)
    }

    message.value = `อัพเดทกล้อง ${editingCamera.value.name} เรียบร้อยแล้ว`
    messageType.value = 'success'

    setTimeout(() => { message.value = '' }, 3000)

  } catch (err) {
    console.error('saveEditCamera error:', err)
    message.value = 'เกิดข้อผิดพลาดในการอัพเดทกล้อง'
    messageType.value = 'danger'
  }
}

// ฟังก์ชันยกเลิกการแก้ไข
function cancelEdit() {
  showEditModal.value = false
  isEditing.value = false
}

function goToMonitor() {
  router.push('/monitor')
}

function handleSearch(query) {
  searchQuery.value = query
}

function clearSearch() {
  searchQuery.value = ''
}
</script>

<template>
  <div class="camera-management">
    <div class="page-header">
      <h1 class="page-title">จัดการกล้อง</h1>
      <button @click="goToMonitor" class="btn btn-secondary">ไปยังหน้ามอนิเตอร์</button>
    </div>

    <div v-if="message" :class="`alert alert-${messageType} notification`">
      {{ message }}
    </div>

    <div class="container">
      <div class="row">
        <!-- ส่วนเพิ่มกล้องใหม่ -->
        <div class="col-md-6">
          <div class="camera-form card">
            <h2 class="card-title">เพิ่มกล้องใหม่</h2>

            <form @submit.prevent="addCamera">

              <div class="form-group">
                <label for="camera-name" class="form-label"
                  >ชื่อกล้อง <span class="required">*</span></label
                >
                <input
                  type="text"
                  id="camera-name"
                  v-model="newCamera.name"
                  class="form-input"
                  placeholder="เช่น กล้องหน้าบ้าน, กล้องหลังบ้าน"
                  autofocus
                />
              </div>

              <div class="form-group">
                <label for="room-name" class="form-label">ชื่อห้อง/โซน</label>
                <input
                  type="text"
                  id="room-name"
                  v-model="newCamera.room_name"
                  class="form-input"
                  placeholder="เช่น ห้อง 101, โถงกลาง, ห้องผู้ป่วย 2"
                />
              </div>

              <div class="form-group">
                <label for="owner-select" class="form-label"
                  >เจ้าของกล้อง <span class="required">*</span></label
                >
                <select
                  id="owner-select"
                  v-model="newCamera.owner_id"
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
                <label class="form-label">แหล่งวิดีโอ</label>
                <div class="source-type-toggle">
                  <label>
                    <input type="radio" value="url" v-model="newCameraSourceType" />
                    กล้องจริง (RTSP/URL)
                  </label>
                  <label>
                    <input type="radio" value="test" v-model="newCameraSourceType" />
                    ไฟล์วิดีโอทดสอบ
                  </label>
                </div>
              </div>

              <div class="form-group" v-if="newCameraSourceType === 'url'">
                <label for="camera-url" class="form-label"
                  >URL การเชื่อมต่อ <span class="required">*</span></label
                >
                <input
                  type="text"
                  id="camera-url"
                  v-model="newCamera.url"
                  class="form-input"
                  placeholder="เช่น rtsp://username:password@ip:port/path"
                />
                <small class="form-help">รองรับ RTSP, RTMP, HLS หรือ URL ของไฟล์วิดีโอ</small>
              </div>

              <div class="form-group" v-else>
                <label for="camera-test-video" class="form-label"
                  >เลือกไฟล์วิดีโอทดสอบ <span class="required">*</span></label
                >
                <select id="camera-test-video" v-model="newCamera.url" class="form-input">
                  <option value="" disabled>เลือกไฟล์วิดีโอ</option>
                  <option v-for="v in testVideos" :key="v.filename" :value="v.url">
                    {{ testVideoLabel(v) }}
                  </option>
                </select>
                <small class="form-help" v-if="testVideos.length === 0">
                  ไม่พบไฟล์วิดีโอทดสอบ — วางไฟล์ .mp4 ไว้ในโฟลเดอร์วิดีโอของ backend (ค่า TEST_VIDEO_DIR) แล้วรีเฟรชหน้านี้
                </small>
                <small class="form-help" v-else>ไฟล์จากโฟลเดอร์วิดีโอของ backend</small>
              </div>


              <div class="form-group">
                <label for="detection-type" class="form-label">ประเภทการตรวจจับ</label>
                <select id="detection-type" v-model="newCamera.detection_type" class="form-input">
                  <option v-for="opt in DETECTION_TYPE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <small class="form-help">{{ DETECTION_TYPE_FORM_HELP }}</small>
              </div>

              <div class="form-group">
                <label for="alert-start-time" class="form-label">เวลาเริ่มการแจ้งเตือน</label>
                <input
                  type="text"
                  id="alert-start-time"
                  v-model="newCamera.alert_start_time"
                  class="form-input"
                  pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
                  placeholder="เช่น 21:00"
                  maxlength="5"
                />
                <small class="form-help">รูปแบบ: ชั่วโมง:นาที (00:00 - 23:59) เช่น 21:00 หรือ 09:00</small>
              </div>

              <div class="form-group">
                <label for="alert-end-time" class="form-label">เวลาสิ้นสุดการแจ้งเตือน</label>
                <input
                  type="text"
                  id="alert-end-time"
                  v-model="newCamera.alert_end_time"
                  class="form-input"
                  pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
                  placeholder="เช่น 05:00"
                  maxlength="5"
                />
                <small class="form-help">รูปแบบ: ชั่วโมง:นาที (00:00 - 23:59) เช่น 05:00 หรือ 17:00</small>
              </div>

              <div class="form-group">
                <label for="notification-cooldown" class="form-label">ระยะห่างการแจ้งเตือน (วินาที)</label>
                <input type="number" id="notification-cooldown" v-model.number="newCamera.notification_cooldown_sec" class="form-input" min="1" step="1" />
                <small class="form-help">เวลาที่ต้องรอก่อนแจ้งเตือนครั้งต่อไป (ป้องกันการแจ้งเตือนซ้ำเร็วเกินไป) เช่น 30 วินาที, 60 วินาที (1 นาที), 600 วินาที (10 นาที)</small>
              </div>

              <!-- Only the legacy detection loops read camera.ai_confidence_threshold. The v3
                   path calls detect_v3_fall_multi without a threshold, so it uses the measured
                   0.65 and this field does nothing -- it was a control that looked live and was
                   not. Disabled rather than removed, because the legacy modes still use it. -->
              <div class="form-group" :class="{ 'form-group-inactive': newCamera.detection_type === 'fall_v2' }">
                <label for="ai-confidence-threshold" class="form-label">ความแม่นยำของ AI (0.0-1.0)</label>
                <input type="number" id="ai-confidence-threshold" v-model.number="newCamera.ai_confidence_threshold" class="form-input" min="0" max="1" step="0.01"
                  :disabled="newCamera.detection_type === 'fall_v2'" />
                <small class="form-help">ใช้กับโหมดตรวจจับรุ่นเก่าเท่านั้น โหมด "ตรวจจับการล้ม (เวอร์ชั่น 3)" ซึ่งเป็นโหมดที่แนะนำ ใช้ค่าที่ผ่านการวัดผลมาแล้ว (0.65) และไม่อ่านค่านี้</small>
              </div>

              <div class="form-buttons">
                <button type="submit" class="btn btn-primary">บันทึกและไปที่มอนิเตอร์</button>
              </div>
            </form>
          </div>
        </div>

        <!-- ส่วนแสดงกล้องปัจจุบัน -->
        <div class="col-md-6">
          <div class="card">
            <h2 class="card-title">กล้องในระบบ</h2>

            <!-- เพิ่มค้นหา -->
            <SearchFilter placeholder="ค้นหากล้อง..." @search="handleSearch" @clear="clearSearch" />

            <div v-if="cameras.length === 0" class="empty-state">
              <IconCamera class="empty-icon" />
              <p>
                {{ searchQuery ? 'ไม่พบกล้องที่ค้นหา' : 'ยังไม่มีกล้องในระบบ กรุณาเพิ่มกล้องใหม่' }}
              </p>
            </div>

            <div v-else class="camera-list">
              <div v-for="(camera, idx) in cameras" :key="camera.id" class="camera-item" :class="{ 'camera-item-alt': idx % 2 === 1 }">
                <div class="camera-info">
                  <h3 class="camera-name">{{ camera.name }}</h3>
                  <p class="camera-url">{{ camera.url }}</p>
                  <p style="font-size:0.95em;color:#64748b;">Detection: {{ getDetectionTypeText(camera.detection_type) }}</p>
                  <p style="font-size:0.95em;color:#64748b;">Alert: {{ camera.alert_start_time || '-' }} - {{ camera.alert_end_time || '-' }}</p>
                  <p style="font-size:0.95em;color:#64748b;">Cooldown: {{ camera.notification_cooldown ?? '-' }} วินาที</p>
                  <p style="font-size:0.95em;color:#1e40af;font-weight:600;" v-if="camera.owner">
                    เจ้าของ: {{ camera.owner.username }} ({{ camera.owner.id }})
                  </p>
                </div>
                <div style="width:100%;margin-top:0.5rem;text-align:right;">
                  <button class="btn btn-danger btn-sm" @click="removeCamera(camera)">ลบ</button>
                  <button class="btn btn-secondary btn-sm" @click="startEditCamera(camera)" style="margin-left: 0.5rem;">แก้ไข</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <CameraEditModal
      v-model="editingCamera"
      :show="showEditModal"
      :show-owner-field="true"
      :users="users"
      @save="saveEditCamera"
      @cancel="cancelEdit"
    />
  </div>
</template>

<style scoped>
.camera-management {
  padding-bottom: 2rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.container {
  width: 100%;
  margin: 0 auto;
}

/* Bootstrap's negative-margin gutter needs a container that pads it back; this one has no
   such container, so the row hung 7px off the right edge on a phone. gap does the same job
   without reaching outside the parent. */
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 30px;
}

.col-md-6 {
  width: 100%;
  min-width: 0;
}

@media (min-width: 768px) {
  .col-md-6 {
    /* half the row minus its share of the gap */
    width: calc(50% - 15px);
  }
}


/* กลุ่มฟอร์มและปุ่ม */
.form-actions {
  display: flex;
  gap: 1rem;
}

/* รายการกล้อง */
.camera-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* กล้องแต่ละตัว: border และพื้นหลังเด่น */
.camera-item {
  border: 2.5px solid #2563eb;
  border-radius: 12px;
  padding: 1.1rem 1rem;
  background: #e0e7ff;
}

/* แถวสลับสี (ถ้ามี) */
.camera-item-alt {
  background: #f1f5ff;
}

/* Responsive & Control Panel */
@media (max-width: 640px) {
  .page-header {
    text-align: center;
  }
  .control-panel {
    display: flex;
    width: 100%;
    justify-content: space-between;
  }
  .camera-card:hover {
    transform: none;
  }
}


.camera-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.camera-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  background-color: #f9fafb;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.camera-item:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
}

.camera-name {
  font-size: 1.125rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.camera-url {
  font-size: 0.875rem;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 300px;
}

.form-buttons {
  margin-top: 1.5rem;
  display: flex;
  justify-content: flex-end;
}

/* A field the selected detection mode ignores is shown greyed rather than hidden, so the
   setting does not silently reappear for the legacy modes that do use it. */
.form-group-inactive {
  opacity: 0.55;
}

.form-help {
  display: block;
  color: #6b7280;
  font-size: 0.875rem;
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

.camera-card {
  transition: all 0.2s ease;
  border: 2px solid transparent;
  position: relative;
  z-index: 0;
}

.camera-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
}

.camera-selected {
  border-color: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.1);
}

.camera-actions {
  display: flex;
  gap: 8px;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background-color: white;
  border-radius: 8px;
  max-width: 500px;
  width: 100%;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  animation: modal-appear 0.3s ease-out;
  max-height: 90vh;
  overflow-y: auto;
}

@keyframes modal-appear {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-header {
  padding: 1rem;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.modal-close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #6b7280;
}

.modal-body {
  padding: 1.5rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  margin-top: 1.5rem;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .control-panel {
    display: flex;
    width: 100%;
    justify-content: space-between;
  }

  .camera-card:hover {
    transform: none;
  }
}
/* เพิ่ม border และสีพื้นหลังสลับแถวให้กล้องแต่ละตัว */
.camera-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-height: 800px;
  overflow-y: auto;
}
/* กล้องแต่ละตัว: สี border และพื้นหลังเด่นขึ้น */
.camera-item {
  border: 2.5px solid #2563eb;
  border-radius: 12px;
  padding: 1.1rem 1rem;
  background: #e0e7ff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: box-shadow 0.2s, border-color 0.2s, background 0.2s;
  box-shadow: 0 2px 12px rgba(37,99,235,0.08);
}
.camera-item-alt {
  background: #c7d2fe;
}
.camera-item:hover {
  border-color: #1e40af;
  background: #dbeafe;
  box-shadow: 0 6px 20px rgba(30,64,175,0.13);
}

@media (max-width: 640px) {
  .camera-item {
    flex-direction: column;
    align-items: flex-start;
    padding: 0.8rem 0.5rem;
    font-size: 0.97rem;
  }
  .camera-actions {
    margin-top: 0.7rem;
    width: 100%;
    justify-content: flex-end;
  }
  .camera-name {
    font-size: 1rem;
  }
  .camera-url {
    max-width: 100%;
    font-size: 0.85rem;
  }
}
.camera-name {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 0.2rem;
}
.camera-url {
  color: #64748b;
  font-size: 0.95rem;
  word-break: break-all;
}
</style>
