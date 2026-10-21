<template>
  <div class="dashboard-view">
    <div class="page-header">
      <h1 class="page-title">แดชบอร์ด</h1>
      <div class="user-info">
        <span class="welcome-text">ยินดีต้อนรับ, {{ currentUser?.username || 'ผู้ใช้' }}</span>
        <span v-if="isAdmin" class="user-role-badge admin">
          ผู้ดูแลระบบ
        </span>
      </div>
    </div>

    <!-- Dashboard สำหรับ Admin -->
    <template v-if="isAdmin">
      <div class="summary-cards">
        <div class="summary-card">
          <div class="summary-icon camera-icon">
            <IconCamera />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ adminDashboardData?.cameras?.total || cameraStore.cameras.length }}</div>
            <div class="summary-label">กล้องทั้งหมด</div>
            <div class="summary-detail" v-if="adminDashboardData?.cameras">
              ใช้งาน: {{ adminDashboardData.cameras.active || 0 }}
            </div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon user-icon">
            <IconCommunity />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ adminDashboardData?.users?.total || 0 }}</div>
            <div class="summary-label">ผู้ใช้ทั้งหมด</div>
            <div class="summary-detail" v-if="adminDashboardData?.users">
              Admin: {{ adminDashboardData.users.admins || 0 }},
              User: {{ adminDashboardData.users.regular_users || 0 }}
            </div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon assessment-icon">
            <IconDocumentation />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ adminDashboardData?.assessments?.total || 0 }}</div>
            <div class="summary-label">การประเมิน Thai-FRAT</div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon alert-icon">
            <IconAlert />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ alertCount }}</div>
            <div class="summary-label">การแจ้งเตือนวันนี้</div>
          </div>
        </div>
      </div>
    </template>

    <!-- Dashboard สำหรับ User -->
    <template v-else>
      <div class="summary-cards">
        <div class="summary-card">
          <div class="summary-icon camera-icon">
            <IconCamera />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ cameraStore.cameras.length }}</div>
            <div class="summary-label">กล้องของคุณ</div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon alert-icon">
            <IconAlert />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ alertCount }}</div>
            <div class="summary-label">การแจ้งเตือนวันนี้</div>
          </div>
        </div>

        <div class="summary-card">
          <div class="summary-icon motion-icon">
            <IconMotion />
          </div>
          <div class="summary-content">
            <div class="summary-value">{{ motionCount }}</div>
            <div class="summary-label">ตรวจพบการเคลื่อนไหว</div>
          </div>
        </div>
      </div>
    </template>

    <div class="dashboard-grid">
      <div class="dashboard-card lg">
        <h2 class="card-title">
          {{ isAdmin ? 'รายการกล้องทั้งหมด' : 'กล้องของคุณ' }}
        </h2>
        <div class="cameras-grid">
          <div v-for="camera in allCameras" :key="camera.id" class="camera-card">
            <div class="camera-header">
              <div class="camera-info">
                <div class="camera-name">{{ camera.name }}</div>
                <div class="camera-room">{{ camera.room_name }}</div>
                <!-- แสดงเจ้าของกล้องสำหรับ admin -->
                <div v-if="isAdmin && camera.owner" class="camera-owner">
                  เจ้าของ: {{ camera.owner.username }}
                </div>
              </div>
              <div class="camera-status-indicator" :class="camera.status || 'offline'"></div>
            </div>
            <div class="camera-mode">
              <span class="mode-label">Detection Mode:</span>
              <span class="mode-value">{{ getDetectionTypeText(camera.detection_type) }}</span>
            </div>
          </div>
          <div v-if="allCameras.length === 0" class="empty-cameras-state">
            <IconCamera class="empty-icon" />
            <p>{{ isAdmin ? 'ยังไม่มีกล้องในระบบ' : 'ยังไม่มีกล้องของคุณ' }}</p>
            <p v-if="!isAdmin" class="empty-help">
              กรุณาติดต่อผู้ดูแลระบบเพื่อเพิ่มกล้องให้คุณ
            </p>
          </div>
        </div>
      </div>

      <div class="dashboard-card">
        <h2 class="card-title">แจ้งเตือนล่าสุด</h2>
        <div class="recent-alerts">
          <div v-for="(alert, index) in recentAlerts" :key="index" class="alert-item">
            <div class="alert-time">{{ alert.time }}</div>
            <div class="alert-info">
              <div class="alert-source">{{ alert.camera_name }}</div>
              <div class="alert-source">{{ alert.camera_room }}</div>
              <div class="alert-message">{{ alert.message }}</div>
            </div>
          </div>
          <div v-if="recentAlerts.length === 0" class="empty-state">ยังไม่มีการแจ้งเตือน</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useAuthStore } from '@/stores/auth'
import adminService from '@/services/adminService'
import { getDetectionTypeText, getAlertTypeText } from '@/utils/detectionType'
import IconCamera from '@/components/icons/IconCamera.vue'
import IconAlert from '@/components/icons/IconAlert.vue'
import IconMotion from '@/components/icons/IconMotion.vue'
import IconCommunity from '@/components/icons/IconCommunity.vue'
import IconDocumentation from '@/components/icons/IconDocumentation.vue'
import logService from '@/services/logService'

const cameraStore = useCameraStore()
const authStore = useAuthStore()

// ตรวจสอบ role
const isAdmin = computed(() => authStore.isAdmin)
const currentUser = computed(() => authStore.user)

// Real data from API
const logs = ref([])
const notifications = ref([])
const combinedActivities = ref([])
const adminDashboardData = ref(null) // ข้อมูล dashboard สำหรับ admin

// Computed values based on real data
const alertCount = computed(() => {
  // Count notifications for today
  const today = new Date().toDateString()
  return notifications.value.filter(notification => {
    const notificationDate = new Date(notification.sent_at).toDateString()
    return notificationDate === today
  }).length
})

const motionCount = computed(() => {
  // Count logs + notifications for today (total detections)
  const today = new Date().toDateString()

  const todayLogs = logs.value.filter(log => {
    const logDate = new Date(log.timestamp).toDateString()
    return logDate === today
  }).length

  const todayNotifications = notifications.value.filter(notification => {
    const notificationDate = new Date(notification.sent_at).toDateString()
    return notificationDate === today
  }).length

  return todayLogs + todayNotifications
})

// Show all cameras instead of just active ones
const allCameras = computed(() => {
  // Ensure cameras is an array before mapping
  if (!Array.isArray(cameraStore.cameras)) {
    return []
  }

  return cameraStore.cameras.map(camera => {
    // Find recent logs for this camera (within last 10 seconds)
    const recentLog = getRecentDetectionForCamera(camera.id)

    return {
      ...camera,
      status: camera.status || 'offline',
      recentDetection: recentLog ? recentLog.detection_result : null,
      detectionTime: recentLog ? recentLog.timestamp : null
    }
  })
})

// Helper function to get recent detection for a specific camera
function getRecentDetectionForCamera(cameraId) {
  const now = new Date()
  const tenSecondsAgo = new Date(now.getTime() - 10000) // 10 seconds ago

  // Find the most recent log for this camera within the last 10 seconds
  const recentLogs = logs.value.filter(log => {
    if (log.camera_id !== cameraId) return false

    const logTime = new Date(log.timestamp)
    return logTime >= tenSecondsAgo && logTime <= now
  })

  // Return the most recent one (logs are usually ordered by time)
  return recentLogs.length > 0 ? recentLogs[recentLogs.length - 1] : null
}

// Recent alerts from real notifications data
const recentAlerts = computed(() => {
  return notifications.value
    .slice(0, 5)
    .map(notification => {
      const camera = cameraStore.cameras.find(c => c.id === notification.camera_id)
      const cameraName = camera ? camera.name : `#${notification.camera_id}`
      const roomName = camera ? camera.room_name : ''
      // notification.detection_type here is an alert-log value (fall_red/alone_yellow/...),
      // not a camera.detection_type setting (bed_exit/fall/fall_v2) -- see utils/detectionType.js
      const typeText = notification.detection_type
        ? getAlertTypeText(notification.detection_type)
        : 'ตรวจพบเหตุการณ์'
      return {
        camera_name: cameraName,
        camera_room: roomName,
        time: formatTime(notification.sent_at),
        message: typeText
      }
    })
})


// Time for today, date and time for anything older. Showing a bare "04:13" next to an alert
// from last week reads as four o'clock this morning, and the card above it says "0 alerts
// today" -- a monitoring dashboard that makes stale alerts look live is worse than one that
// shows nothing.
function formatTime(timestamp) {
  const date = new Date(timestamp)
  const hours = date.getHours().toString().padStart(2, '0')
  const minutes = date.getMinutes().toString().padStart(2, '0')
  const time = `${hours}:${minutes}`
  const now = new Date()
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
  if (sameDay) return time
  const day = date.getDate().toString().padStart(2, '0')
  const month = (date.getMonth() + 1).toString().padStart(2, '0')
  return `${day}/${month} ${time}`
}

// Fetch data functions (same as MonitorView)
async function fetchAllLogs() {
  try {
    const res = await logService.fetchAllLogs()

    // Check if response is directly an array of logs
    if (Array.isArray(res) && res.length > 0) {
      logs.value = res
    } else if (res && res.logs && Array.isArray(res.logs)) {
      // Fallback: check if response has logs property (wrapped format)
      logs.value = res.logs
    } else {
      logs.value = []
    }
  } catch (error) {
    console.error('Dashboard: Error fetching logs:', error)
    logs.value = []
  }
}

async function fetchAllNotifications() {
  try {
    const res = await logService.fetchAllNotification()

    // Handle both direct array and wrapped object formats
    let notificationsArray = []
    if (Array.isArray(res)) {
      notificationsArray = res
    } else if (res && res.notifications && Array.isArray(res.notifications)) {
      notificationsArray = res.notifications
    } else if (res && Array.isArray(res.data)) {
      notificationsArray = res.data
    }

    notifications.value = notificationsArray
  } catch (error) {
    console.error('Dashboard: Error fetching notifications:', error)
    notifications.value = []
  }
}

// Polling setup
let dataPollingInterval = null

async function loadAdminDashboard() {
  if (isAdmin.value) {
    try {
      adminDashboardData.value = await adminService.getDashboard()
    } catch (error) {
      console.error('Failed to load admin dashboard:', error)
    }
  }
}

function startDataPolling() {
  if (dataPollingInterval) clearInterval(dataPollingInterval)

  // Fetch immediately on start
  fetchAllLogs()
  fetchAllNotifications()
  loadAdminDashboard()

  // Poll every 15 seconds for more real-time dashboard updates
  dataPollingInterval = setInterval(async () => {
    await fetchAllLogs()
    await fetchAllNotifications()
    await loadAdminDashboard()
  }, 15000)
}

function stopDataPolling() {
  if (dataPollingInterval) {
    clearInterval(dataPollingInterval)
    dataPollingInterval = null
  }
}

onMounted(async () => {
  // โหลดข้อมูลกล้องเฉพาะเมื่อ user ล็อกอินแล้ว
  if (authStore.isLoggedIn) {
    await cameraStore.loadCameras()
  }
  startDataPolling()
})

onBeforeUnmount(() => {
  stopDataPolling()
})
</script>

<style scoped>
.dashboard-view {
  padding-bottom: 2rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.welcome-text {
  color: #374151;
  font-weight: 500;
}

.user-role-badge {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.user-role-badge.admin {
  background-color: #fef3c7;
  color: #92400e;
  border: 1px solid #fbbf24;
}

.user-role-badge.user {
  background-color: #dcfce7;
  color: #166534;
  border: 1px solid #22c55e;
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.5rem;
  margin-top: 1.5rem;
  margin-bottom: 2rem;
}

.summary-card {
  background-color: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 1.5rem;
  display: flex;
  align-items: center;
}

.summary-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 1rem;
}

.summary-icon svg {
  width: 24px;
  height: 24px;
  color: white;
}

.camera-icon {
  background-color: #3b82f6;
}

.alert-icon {
  background-color: #ef4444;
}

.user-icon {
  background: #8b5cf6;
}

.assessment-icon {
  background: #0ea5e9;
}

.motion-icon {
  background-color: #f59e0b;
}

.summary-content {
  flex: 1;
}

.summary-value {
  font-size: 2rem;
  font-weight: 700;
  color: #1f2937;
  line-height: 1;
}

.summary-label {
  color: #6b7280;
  font-size: 0.875rem;
  font-weight: 500;
  margin-top: 0.25rem;
}

.summary-detail {
  color: #6b7280;
  font-size: 0.75rem;
  margin-top: 0.25rem;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1.5rem;
}

.dashboard-card {
  background-color: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 1.5rem;
}

.dashboard-card.lg {
  grid-column: span 1;
}

/* Cameras Grid - Compact and Efficient Layout */
.cameras-grid {
  margin-top: 1rem;
  display: grid;
  /* min() so a 360px track cannot exceed the viewport: on a 390px phone the fixed
     minimum plus card padding pushed the grid 27px past the screen edge. */
  grid-template-columns: repeat(auto-fill, minmax(min(360px, 100%), 1fr));
  gap: 0.75rem;
}

.camera-card {
  background: white;
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.camera-card:hover {
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  border-color: #d1d5db;
}

.camera-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 0.75rem;
}

.camera-info {
  flex: 1;
}

.camera-name {
  font-size: 1rem;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.25rem;
  line-height: 1.3;
}

.camera-room {
  font-size: 0.875rem;
  color: #6b7280;
  font-weight: 500;
}

.camera-owner {
  color: #059669;
  font-size: 0.75rem;
  font-weight: 500;
  margin-top: 0.25rem;
}

.camera-status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 0.125rem;
  flex-shrink: 0;
}

.camera-status-indicator.online {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

.camera-status-indicator.offline {
  background: #9ca3af;
  box-shadow: 0 0 0 2px rgba(156, 163, 175, 0.2);
}

.camera-mode {
  padding: 0.5rem;
  background: #f9fafb;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
  font-size: 0.875rem;
}

.mode-label {
  color: #6b7280;
  font-weight: 500;
  margin-right: 0.5rem;
}

.mode-value {
  color: #1f2937;
  font-weight: 600;
}

.empty-cameras-state {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  background: #f9fafb;
  border-radius: 8px;
  border: 2px dashed #d1d5db;
  color: #6b7280;
}

.empty-cameras-state .empty-icon {
  width: 32px;
  height: 32px;
  color: #d1d5db;
  margin-bottom: 0.5rem;
}

.empty-help {
  margin-top: 0.5rem;
  font-size: 0.875rem;
  color: #9ca3af;
}

/* Alerts List - Compact and Clean Design */
.alerts-list {
  margin-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.alert-item {
  background: white;
  border-radius: 6px;
  padding: 0.75rem;
  border: 1px solid #fed7d7;
  border-left: 3px solid #e53e3e;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  display: flex;
  gap: 0.75rem;
  transition: all 0.2s ease;
}

.alert-item:hover {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  border-color: #feb2b2;
}

.alert-time {
  font-size: 0.875rem;
  font-weight: 600;
  color: #e53e3e;
  min-width: 45px;
  flex-shrink: 0;
}

.alert-details {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.alert-source {
  font-size: 0.875rem;
  font-weight: 600;
  color: #2d3748;
  line-height: 1.3;
}

.alert-location {
  font-size: 0.8rem;
  color: #718096;
  font-weight: 500;
}

.alert-message {
  font-size: 0.8rem;
  color: #4a5568;
  font-weight: 500;
  background: #f7fafc;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  margin-top: 0.125rem;
}

.empty-alerts-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  background: #f7fafc;
  border-radius: 6px;
  border: 2px dashed #cbd5e0;
  color: #718096;
  font-size: 0.875rem;
}

/* Responsive Design */
@media (max-width: 768px) {
  .dashboard-card.lg {
    grid-column: span 1;
  }

  /* The cameras/alerts split is 2fr 1fr on desktop. Left alone on a phone it squeezes the
     alert column to ~150px, which wraps every word onto its own line -- and a caregiver is
     more likely to open this on a phone than anywhere else. */
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
</style>
