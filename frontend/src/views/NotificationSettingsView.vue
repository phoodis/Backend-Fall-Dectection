<template>
  <div class="notification-settings">
    <h1 class="page-title">ตั้งค่าการแจ้งเตือน</h1>

    <!-- Every signed-in user sets up THEIR OWN LINE here (owner, 8 Oct: one system bot; each user only enters their
         own LINE id). The bot's token, the webhook setup and the list of groups stay admin-only. -->
    <div class="settings-container">
      <!-- การตั้งค่าช่วงเวลา -->
      <!-- <div class="card">
        <h2 class="card-title">ช่วงเวลาการแจ้งเตือน</h2>

        <div v-if="saveSuccess" class="alert alert-success">บันทึกการตั้งค่าเรียบร้อยแล้ว</div>

        <div class="form-group">
          <label class="form-label">ช่วงเวลาแจ้งเตือน (รูปแบบ 24 ชั่วโมง)</label>
          <div class="time-range">
            <input
              type="text"
              v-model="settings.timeRange.start"
              class="form-input time-input"
              pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
              placeholder="21:00"
              maxlength="5"
            />
            <span>ถึง</span>
            <input
              type="text"
              v-model="settings.timeRange.end"
              class="form-input time-input"
              pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
              placeholder="05:00"
              maxlength="5"
            />
          </div>
          <small class="text-muted">รูปแบบ: ชั่วโมง:นาที (00:00 - 23:59) เช่น 21:00 ถึง 05:00</small>
        </div>

        <div class="form-actions-inline">
          <button
            @click="saveSettings"
            class="btn btn-primary"
            :disabled="isSaving"
            :class="{ 'loading': isSaving }"
          >
            <span v-if="!isSaving">บันทึกการตั้งค่าช่วงเวลา</span>
            <span v-else>กำลังบันทึก...</span>
          </button>
          <button @click="resetTimeSettings" class="btn btn-secondary" :disabled="isSaving">
            รีเซ็ตเวลา
          </button>
        </div>
      </div>-->

      <!-- การตั้งค่า LINE Messaging API -->
      <div class="card">
        <h2 class="card-title">การตั้งค่าแจ้งเตือนผ่าน LINE</h2>

        <div v-if="lineSaveSuccess" class="alert alert-success">
          บันทึกการตั้งค่า LINE สำเร็จแล้ว
        </div>

        <div v-if="lineErrorMessage" class="alert alert-error">
          {{ lineErrorMessage }}
        </div>

        <div v-if="lineUnavailable" class="line-unavailable">
          <strong>การแจ้งเตือนผ่าน LINE ยังไม่เปิดใช้งานในระบบนี้</strong>
          <p>ส่วนนี้จะใช้ได้เมื่อ server เปิดบริการ LINE แล้ว ระหว่างนี้ระบบยังบันทึกการแจ้งเตือนและแสดงในหน้าเว็บตามปกติ</p>
        </div>

        <div v-if="!lineUnavailable" class="info-section">
          <p class="info-text">
            ระบบส่งแจ้งเตือนผ่าน LINE Messaging API โดยตรง (ไม่ผ่านบริการอื่น)
          </p>

          <div class="setup-instructions">
            <h3>วิธีการตั้งค่า:</h3>
            <ol>
              <li>สร้าง Messaging API channel ที่ <strong>LINE Developers Console</strong></li>
              <li>คัดลอก <code>Channel access token</code> มาใส่ในช่องด้านล่าง</li>
              <li>
                เลือกปลายทางอย่างน้อยหนึ่งอย่าง — เพิ่มบอทเป็นเพื่อนแล้วกรอก <code>User ID</code>
                ของคุณ และ/หรือ <strong>เชิญบอทเข้ากลุ่ม LINE</strong> แล้วเลือกกลุ่มจากรายการที่ขึ้นมา
              </li>
              <li>เปิดสวิตช์ แล้วกดบันทึก</li>
            </ol>
          </div>
        </div>

        <div v-if="!lineUnavailable" class="line-form">
          <div class="form-group">
            <label class="toggle-row">
              <input type="checkbox" v-model="lineSettings.enabled" :disabled="isLineLoading" />
              <span>เปิดการแจ้งเตือนผ่าน LINE</span>
            </label>
            <small class="form-help">
              ปิดอยู่ = ระบบจะไม่ส่งข้อความไปที่ LINE เลย แม้จะบันทึก token ไว้แล้ว
            </small>
          </div>

          <div v-if="!isAdmin" class="form-group">
            <p class="form-help">ระบบใช้บอท LINE ของระบบอยู่แล้ว — คุณใส่แค่ <b>LINE ID ของคุณ</b> ด้านล่าง
              (แอดบอทเป็นเพื่อนแล้วพิมพ์อะไรก็ได้หาบอท บอทจะตอบ LINE ID ของคุณกลับมาให้คัดลอก)</p>
          </div>
          <div v-if="isAdmin" class="form-group">
            <label for="line-token" class="form-label">
              Channel access token
              <span class="required">*</span>
            </label>
            <input
              type="password"
              id="line-token"
              v-model="lineSettings.channel_access_token"
              class="form-input"
              :placeholder="currentLineSettings && currentLineSettings.has_token ? 'บันทึกไว้แล้ว (เว้นว่างไว้ถ้าไม่ต้องการเปลี่ยน)' : 'กรอก Channel access token'"
              :disabled="isLineLoading"
            />
          </div>
          <!-- Everyone: where THEIR alerts go. (8 Oct: these used to share the token's block, so hiding the token
               from ordinary users hid their own LINE id field too.) -->
          <div class="form-group">
            <label for="line-user-id" class="form-label">
              LINE User ID
            </label>
            <input
              type="text"
              id="line-user-id"
              v-model="lineSettings.line_user_id"
              class="form-input"
              placeholder="เช่น Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              :disabled="isLineLoading"
            />

            <label for="line-group-id" class="form-label">
              LINE Group ID (ส่งเข้ากลุ่ม)
            </label>
            <input
              type="text"
              id="line-group-id"
              v-model="lineSettings.line_group_id"
              class="form-input"
              placeholder="เช่น Cxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              :disabled="isLineLoading"
            />
            <small class="form-hint">
              กรอกอย่างน้อยหนึ่งช่อง จะกรอกทั้งสองก็ได้ ระบบจะส่งไปทุกปลายทางที่กรอกไว้ —
              คนเดียวอาจหลับหรือไม่มีสัญญาณ การที่กลุ่มเห็นด้วยคือเหตุผลที่มีช่องนี้
            </small>

            <div class="discovered" v-if="isAdmin && currentLineSettings && currentLineSettings.discovered_targets && currentLineSettings.discovered_targets.length">
              <p class="discovered-title">กลุ่มที่บอทถูกเชิญเข้าไปแล้ว — กดเพื่อใช้</p>
              <button
                v-for="t in currentLineSettings.discovered_targets"
                :key="t.target_id"
                type="button"
                class="discovered-item"
                :class="{ 'is-left': t.left }"
                :disabled="isLineLoading"
                @click="lineSettings.line_group_id = t.target_id"
              >
                <span class="discovered-id">{{ t.target_id }}</span>
                <span class="discovered-note">
                  {{ t.left ? 'บอทออกจากกลุ่มแล้ว' : (t.target_type === 'room' ? 'ห้องแชท' : 'กลุ่ม') }}
                </span>
              </button>
            </div>
            <small class="form-hint form-hint-spaced" v-else>
              ยังไม่พบกลุ่ม — Group ID หาจากที่ไหนไม่ได้เลยนอกจากตอนบอทเข้ากลุ่ม
              เชิญบอทเข้ากลุ่มก่อน แล้วกดโหลดหน้านี้ใหม่ ต้องตั้ง Webhook URL ให้ LINE เรียกเข้ามาได้ด้วย
            </small>
          </div>

          <div class="line-actions">
            <button
              @click="saveLineSettings"
              type="button"
              class="btn btn-primary"
              :disabled="isLineLoading"
              :class="{ 'loading': isLineLoading }"
            >
              <span v-if="!isLineLoading">บันทึกการตั้งค่า LINE</span>
              <span v-else>กำลังบันทึก...</span>
            </button>

            <button
              @click="testLineSettings"
              type="button"
              class="btn btn-secondary"
              :disabled="isLineLoading || isLineTesting || !(currentLineSettings && currentLineSettings.enabled)"
              :class="{ 'loading': isLineTesting }"
            >
              <span v-if="!isLineTesting">ทดสอบการส่งข้อความ</span>
              <span v-else>กำลังทดสอบ...</span>
            </button>
          </div>
        </div>

        <div v-if="currentLineSettings" class="current-line-settings">
          <h3 class="sub-title">การตั้งค่าปัจจุบัน</h3>

          <div class="setting-item">
            <span class="setting-label">Channel access token:</span>
            <span class="setting-value">
              {{ currentLineSettings.has_token ? '••••••••••' + currentLineSettings.token_preview : 'ยังไม่ได้ตั้งค่า' }}
            </span>
          </div>

          <div class="setting-item">
            <span class="setting-label">LINE User ID:</span>
            <span class="setting-value">{{ currentLineSettings.line_user_id || 'ยังไม่ได้ตั้งค่า' }}</span>
          </div>

          <div class="setting-item">
            <span class="setting-label">LINE Group ID:</span>
            <span class="setting-value">{{ currentLineSettings.line_group_id || 'ยังไม่ได้ตั้งค่า' }}</span>
          </div>

          <div class="setting-item">
            <span class="setting-label">ส่งไปกี่ปลายทาง:</span>
            <span class="setting-value" :class="currentLineSettings.target_count ? 'status-ready' : 'status-not-set'">
              {{ currentLineSettings.target_count || 0 }}
            </span>
          </div>

          <div class="setting-item">
            <span class="setting-label">สถานะ:</span>
            <span class="setting-value" :class="currentLineSettings.enabled ? 'status-ready' : 'status-not-set'">
              {{ currentLineSettings.enabled ? 'เปิดใช้งาน' : 'ปิดอยู่ (ไม่ส่งแจ้งเตือน)' }}
            </span>
          </div>

          <div class="setting-item">
            <span class="setting-label">อัปเดตล่าสุด:</span>
            <span class="setting-value">{{ formatDateTime(currentLineSettings.updated_at) }}</span>
          </div>
        </div>

        <!-- The acknowledge button and the 60-second clip need two things beyond a channel
             token, and without them LINE alerts still arrive while the button silently does
             nothing. Showing which piece is missing is the difference between a feature that
             looks broken and one that tells you how to finish setting it up. -->
        <div v-if="isAdmin && currentLineSettings" class="settings-section">
          <h3 class="sub-title">ปุ่ม "รับทราบ" และคลิปย้อนหลัง 60 วินาที</h3>

          <div class="setting-item">
            <span class="setting-label">สถานะ:</span>
            <span class="setting-value" :class="currentLineSettings.acknowledge_ready ? 'status-ready' : 'status-not-set'">
              {{ currentLineSettings.acknowledge_ready ? 'พร้อมใช้งาน' : 'ยังใช้ไม่ได้ — ตั้งค่าตามด้านล่าง' }}
            </span>
          </div>

          <div class="setting-item">
            <span class="setting-label">Channel secret (ตรวจลายเซ็น):</span>
            <span class="setting-value" :class="currentLineSettings.channel_secret_set ? 'status-ready' : 'status-not-set'">
              {{ currentLineSettings.channel_secret_set ? 'ตั้งค่าแล้ว' : 'ยังไม่ได้ตั้ง (LINE_CHANNEL_SECRET)' }}
            </span>
          </div>

          <div class="setting-item">
            <span class="setting-label">ที่อยู่สาธารณะของเซิร์ฟเวอร์:</span>
            <span class="setting-value" :class="currentLineSettings.public_base_url ? 'status-ready' : 'status-not-set'">
              {{ currentLineSettings.public_base_url || 'ยังไม่ได้ตั้ง (PUBLIC_BASE_URL)' }}
            </span>
          </div>

          <div class="setting-item" v-if="currentLineSettings.webhook_url">
            <span class="setting-label">Webhook URL (ใส่ใน LINE Developers Console):</span>
            <span class="setting-value">{{ currentLineSettings.webhook_url }}</span>
          </div>

          <p class="ack-help" v-if="!currentLineSettings.acknowledge_ready">
            ทั้งสองค่านี้ตั้งในไฟล์ <code>.env</code> ของเซิร์ฟเวอร์ ไม่ใช่ในหน้านี้ เพราะเป็นค่าระดับเครื่อง
            ไม่ใช่ของผู้ใช้แต่ละคน เมื่อตั้งแล้วให้นำ Webhook URL ไปใส่ในช่อง Webhook ของ
            LINE Developers Console แล้วเปิด "Use webhook"
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useNotificationStore } from '@/stores/notification'
import { useCameraStore } from '@/stores/camera'
import { useAuthStore } from '@/stores/auth'
import cameraService from '@/services/cameraService'
import lineService from '@/services/lineService'

const notificationStore = useNotificationStore()
const cameraStore = useCameraStore()
const authStore = useAuthStore()

const saveSuccess = ref(false)
const isSaving = ref(false)

// ตรวจสอบสิทธิ์ admin
const isAdmin = computed(() => authStore.isAdmin)

const settings = ref({
  timeRange: {
    start: '21:00',
    end: '05:00',
  }
})
// LINE settings. The token is never sent back from the server, so the input starts blank
// and an empty value on save means "keep what is stored" (see the route's comment).
const lineSettings = ref({
  channel_access_token: '',
  line_user_id: '',
  line_group_id: '',
  enabled: false
})
const currentLineSettings = ref(null)
const isLineLoading = ref(false)
const isLineTesting = ref(false)
const lineSaveSuccess = ref(false)
const lineErrorMessage = ref('')
const lineUnavailable = ref(false)

function applyLineSettings(data) {
  currentLineSettings.value = data
  lineSettings.value.line_user_id = data.line_user_id || ''
  lineSettings.value.line_group_id = data.line_group_id || ''
  lineSettings.value.enabled = !!data.enabled
  lineSettings.value.channel_access_token = ''
}

async function loadLineSettings() {
  try {
    const res = await lineService.fetchLineSettings()
    applyLineSettings(res.data)
  } catch (error) {
    if (error.unavailable) {
      lineUnavailable.value = true
    } else {
      lineErrorMessage.value = error.message
    }
  }
}

async function saveLineSettings() {
  isLineLoading.value = true
  lineErrorMessage.value = ''
  lineSaveSuccess.value = false
  try {
    const res = await lineService.updateLineSettings({
      channel_access_token: lineSettings.value.channel_access_token,
      line_user_id: lineSettings.value.line_user_id,
      line_group_id: lineSettings.value.line_group_id,
      enabled: lineSettings.value.enabled
    })
    applyLineSettings(res.data)
    lineSaveSuccess.value = true
    setTimeout(() => { lineSaveSuccess.value = false }, 3000)
  } catch (error) {
    lineErrorMessage.value = error.message
    // Keep the toggle showing what the server actually stored, not what the user tried to
    // set -- otherwise a rejected save leaves the UI claiming LINE is on when it is off.
    if (currentLineSettings.value) lineSettings.value.enabled = currentLineSettings.value.enabled
  } finally {
    isLineLoading.value = false
  }
}

async function testLineSettings() {
  isLineTesting.value = true
  lineErrorMessage.value = ''
  try {
    await lineService.testLineSettings()
    notificationStore.sendNotification({
      title: 'ส่งข้อความทดสอบแล้ว',
      message: 'กรุณาตรวจสอบ LINE ของคุณ',
      type: 'success'
    })
  } catch (error) {
    lineErrorMessage.value = error.message
  } finally {
    isLineTesting.value = false
  }
}







function formatDateTime(dateTimeString) {
  if (!dateTimeString) return 'ไม่มีข้อมูล'

  try {
    const date = new Date(dateTimeString)
    return date.toLocaleString('th-TH', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (error) {
    return 'ไม่สามารถแสดงวันที่ได้'
  }
}

// โหลดการตั้งค่าจาก localStorage
onMounted(() => {
  // LINE settings are per user and load for everyone; the time-range settings below remain admin-only.
  if (!isAdmin.value) {
    loadLineSettings()
    return
  }

  const savedSettings = localStorage.getItem('notificationSettings')
  if (savedSettings) {
    try {
      const parsed = JSON.parse(savedSettings)

      // Handle both old and new format
      if (parsed.start && parsed.end) {
        // Old format from MonitorView: { start: "21:00", end: "05:00" }
        settings.value.timeRange.start = parsed.start
        settings.value.timeRange.end = parsed.end
      } else if (parsed.timeRange) {
        // New format: { timeRange: { start: "21:00", end: "05:00" }, ... }
        settings.value = { ...settings.value, ...parsed }
      }
    } catch (e) {
      console.error('Error parsing notification settings:', e)
    }
  }

  // Load cameras for update functionality (เฉพาะเมื่อเป็น admin)
  if (isAdmin.value) {
    cameraStore.loadCameras()
  }
  loadLineSettings()
})

// บันทึกการตั้งค่าช่วงเวลา
async function saveSettings() {
  if (isSaving.value) return // Prevent multiple simultaneous saves

  isSaving.value = true

  try {
    // Save to localStorage in both formats for compatibility
    localStorage.setItem('notificationSettings', JSON.stringify(settings.value))

    // Also save in MonitorView format for backward compatibility
    const monitorFormat = {
      start: settings.value.timeRange.start,
      end: settings.value.timeRange.end
    }
    localStorage.setItem('monitorNotificationSettings', JSON.stringify(monitorFormat))

    // Update all cameras with new alert time settings
    const cameras = cameraStore.cameras
    if (cameras.length > 0) {
      const updatePromises = cameras.map(async (camera) => {
        try {
          const updatedData = {
            name: camera.name,
            url: camera.url,
            room_name: camera.room_name,
            detection_type: camera.detection_type,
            alert_start_time: settings.value.timeRange.start,
            alert_end_time: settings.value.timeRange.end,
            notification_cooldown: camera.notification_cooldown,
            ai_confidence_threshold: camera.ai_confidence_threshold
          }

          await cameraService.updateCamera(camera.id, updatedData)
          return { success: true, camera: camera.name }
        } catch (error) {
          console.error(`Failed to update camera ${camera.name}:`, error)
          return { success: false, camera: camera.name, error }
        }
      })

      // Wait for all updates to complete
      const results = await Promise.all(updatePromises)
      const successCount = results.filter(r => r.success).length
      const failedCount = results.filter(r => !r.success).length

      if (failedCount === 0) {
        notificationStore.sendNotification({
          title: 'บันทึกการตั้งค่าสำเร็จ',
          message: `อัปเดตการตั้งค่าและเวลาการแจ้งเตือนสำหรับกล้องทั้งหมด ${successCount} ตัวแล้ว`,
          type: 'success'
        })
      } else {
        notificationStore.sendNotification({
          title: 'บันทึกการตั้งค่าบางส่วน',
          message: `อัปเดตสำเร็จ ${successCount} ตัว, ล้มเหลว ${failedCount} ตัว`,
          type: 'warning'
        })
      }

      // Reload cameras to get updated data
      await cameraStore.loadCameras()
    }

    // แสดงข้อความบันทึกสำเร็จ
    saveSuccess.value = true
    setTimeout(() => {
      saveSuccess.value = false
    }, 3000)

  } catch (error) {
    console.error('Error saving notification settings:', error)
    notificationStore.sendNotification({
      title: 'เกิดข้อผิดพลาด',
      message: 'ไม่สามารถบันทึกการตั้งค่าการแจ้งเตือนได้',
      type: 'error'
    })
  } finally {
    isSaving.value = false
  }
}

// รีเซ็ตการตั้งค่าเวลา
function resetTimeSettings() {
  settings.value = {
    timeRange: {
      start: '21:00',
      end: '05:00',
    }
  }
}
</script>

<style scoped>
/* The two hints under the group field are separate thoughts -- "you may fill in either" and
   "here is why the list is empty" -- and with no gap they render as one wall of Thai. */
.form-hint-spaced { display: block; margin-top: 0.5rem; }
.discovered {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.discovered-title {
  margin: 0 0 0.15rem;
  font-size: 0.85rem;
  color: #555;
}
.discovered-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.65rem;
  border: 1px solid #d5d5d5;
  border-radius: 6px;
  background: #fafafa;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
}
.discovered-item:hover:not(:disabled) { border-color: #06c755; background: #f2fbf5; }
.discovered-item:disabled { cursor: default; opacity: 0.6; }
.discovered-item.is-left { opacity: 0.55; }
.discovered-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  word-break: break-all;
}
.discovered-note { font-size: 0.75rem; color: #666; white-space: nowrap; }

.notification-settings {
  padding-bottom: 2rem;
}

.settings-container {
  max-width: 800px;
}

/* Access denied styles */
.access-denied {
  max-width: 600px;
  margin: 2rem auto;
  text-align: center;
}

.access-denied h3 {
  margin-bottom: 1rem;
  font-size: 1.5rem;
  color: #f59e0b;
}

.text-muted {
  color: #6b7280;
  font-size: 0.875rem;
}

.time-range {
  display: flex;
  align-items: center;
  gap: 8px;
}

.time-input {
  width: 100%;
  max-width: 120px;
}

/* Inline form actions for time settings */
.form-actions-inline {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
}

.form-actions-inline .btn {
  flex: 0 0 auto;
}

.form-actions-inline .btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-actions-inline .btn.loading {
  background-color: #9ca3af;
}

/* LINE settings styles */
.info-section {
  margin-bottom: 2rem;
  padding: 1rem;
  background-color: #f8fafc;
  border-left: 4px solid #3b82f6;
  border-radius: 0 4px 4px 0;
}

.info-text {
  margin-bottom: 1rem;
  color: #374151;
  font-size: 0.95rem;
}

.setup-instructions {
  margin-top: 1.5rem;
}

.setup-instructions h3 {
  margin-bottom: 0.75rem;
  color: #1f2937;
  font-size: 1rem;
  font-weight: 600;
}

.setup-instructions ol {
  margin-left: 1.5rem;
  color: #4b5563;
  font-size: 0.9rem;
  line-height: 1.6;
}

.setup-instructions li {
  margin-bottom: 0.5rem;
}

.setup-instructions code {
  background-color: #e5e7eb;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
}

.setup-instructions strong {
  font-weight: 600;
}

.line-form {
  margin-top: 2rem;
}

.required {
  color: #dc2626;
  margin-left: 0.25rem;
}

.form-help {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: #6b7280;
}

.line-actions {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
  margin-bottom: 2rem;
}

.btn.loading {
  background-color: #9ca3af;
}

.current-line-settings {
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid #e5e7eb;
}

.sub-title {
  margin-bottom: 1rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1f2937;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 0;
  border-bottom: 1px solid #e5e7eb;
}

.setting-item:last-child {
  border-bottom: none;
}

.ack-help {
  margin: 0.75rem 0 0;
  font-size: 0.875rem;
  line-height: 1.7;
  color: #64748b;
}

.ack-help code {
  background: #f1f5f9;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
}

.setting-label {
  font-weight: 500;
  color: #374151;
}

.setting-value {
  color: #6b7280;
  font-family: monospace;
}

/* Reuses .status-ready / .status-not-set below rather than introducing a second pair of
   status colours for the same idea. */
.toggle-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  cursor: pointer;
}

.toggle-row input {
  width: 1.1rem;
  height: 1.1rem;
  cursor: pointer;
}

.status-ready {
  color: #10b981;
  font-weight: 600;
}

.status-not-set {
  color: #ef4444;
  font-weight: 600;
}

.alert {
  padding: 1rem;
  border-radius: 0.375rem;
  margin-bottom: 1.5rem;
}

.alert-success {
  background-color: #d1fae5;
  border: 1px solid #10b981;
  color: #047857;
}

.alert-error {
  background-color: #fee2e2;
  border: 1px solid #ef4444;
  color: #dc2626;
}

.alert-warning {
  background-color: #fef3c7;
  border: 1px solid #f59e0b;
  color: #92400e;
}

@media (max-width: 768px) {
  .form-actions-inline {
    flex-direction: column;
  }

  .form-actions-inline .btn {
    width: 100%;
  }

  .line-actions {
    flex-direction: column;
  }

  .line-actions .btn {
    width: 100%;
  }

  .setting-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.25rem;
  }
}
.line-unavailable {
  margin: 1rem 0;
  padding: 1rem 1.25rem;
  border: 1px solid #93c5fd;
  border-radius: 8px;
  background: #eff6ff;
  color: #1e3a8a;
}

.line-unavailable p {
  margin: 0.4rem 0 0;
}
</style>

