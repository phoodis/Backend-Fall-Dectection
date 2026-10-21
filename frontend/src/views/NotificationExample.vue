<template>
  <div class="notification-examples">
    <h1 class="page-title">ตัวอย่างการแจ้งเตือน</h1>

    <div class="examples-container">
      <div class="controls card">
        <h2 class="card-title">การตั้งค่าตัวอย่าง</h2>

        <div class="form-group">
          <label class="form-label">ประเภทการแจ้งเตือน</label>
          <div class="radio-group">
            <label v-for="type in notificationTypes" :key="type.value">
              <input type="radio" v-model="notificationType" :value="type.value" />
              {{ type.label }}
            </label>
          </div>
        </div>

        <div class="form-group">
          <label for="notification-title" class="form-label">หัวข้อ</label>
          <input
            type="text"
            id="notification-title"
            v-model="notificationTitle"
            class="form-input"
            placeholder="หัวข้อการแจ้งเตือน"
          />
        </div>

        <div class="form-group">
          <label for="notification-message" class="form-label">ข้อความ</label>
          <input
            type="text"
            id="notification-message"
            v-model="notificationMessage"
            class="form-input"
            placeholder="ข้อความการแจ้งเตือน"
          />
        </div>

        <div class="form-group">
          <label for="notification-duration" class="form-label">ระยะเวลาแสดง (มิลลิวินาที)</label>
          <input
            type="number"
            id="notification-duration"
            v-model="notificationDuration"
            class="form-input"
            min="0"
            step="500"
          />
        </div>

        <div class="form-group form-checkbox">
          <input type="checkbox" id="auto-close" v-model="autoClose" />
          <label for="auto-close">ปิดอัตโนมัติ</label>
        </div>

        <div class="form-group form-checkbox">
          <input type="checkbox" id="show-time" v-model="showTime" />
          <label for="show-time">แสดงเวลา</label>
        </div>

        <div class="form-group form-checkbox">
          <input type="checkbox" id="requires-ack" v-model="requiresAcknowledgment" />
          <label for="requires-ack">ต้องยืนยันการรับทราบ (แจ้งเตือนซ้ำถ้าไม่ยืนยัน)</label>
        </div>

        <div class="form-group">
          <label class="form-label">ตำแหน่งการแสดง</label>
          <div class="radio-group">
            <label v-for="option in positionOptions" :key="option.value">
              <input type="radio" v-model="notificationPosition" :value="option.value" />
              {{ option.label }}
            </label>
          </div>
        </div>

        <div class="form-buttons">
          <button @click="showNotification" class="btn btn-primary">แสดงการแจ้งเตือน</button>
          <button @click="showMultipleNotifications" class="btn btn-secondary">
            แสดงหลายรายการ
          </button>
        </div>
      </div>

      <div class="notifications-preview card">
        <h2 class="card-title">การแจ้งเตือนตัวอย่าง</h2>

        <div class="notifications-container">
          <Notification
            v-for="(notification, index) in notifications"
            :key="index"
            :title="notification.title"
            :message="notification.message"
            :type="notification.type"
            :duration="notification.duration"
            :auto-close="notification.autoClose"
            :show-time="notification.showTime"
            @close="removeNotification(index)"
          />

          <p v-if="notifications.length === 0" class="empty-message">
            ไม่มีการแจ้งเตือน กดปุ่ม "แสดงการแจ้งเตือน" เพื่อทดสอบ
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Notification from '@/components/common/Notification.vue'
import { useLeftNotificationStore } from '@/stores/leftNotification'
import { useNotificationStore } from '@/stores/notification'

const notifications = ref([])
const notificationType = ref('info')
const notificationTitle = ref('การแจ้งเตือนใหม่')
const notificationMessage = ref('นี่คือข้อความแจ้งเตือนตัวอย่าง')
const notificationDuration = ref(5000)
const autoClose = ref(true)
const showTime = ref(true)
const notificationPosition = ref('right')
const requiresAcknowledgment = ref(false)

const leftNotificationStore = useLeftNotificationStore()
const notificationStore = useNotificationStore() // เพิ่มการใช้ notification store

const notificationTypes = [
  { value: 'info', label: 'ข้อมูล' },
  { value: 'success', label: 'สำเร็จ' },
  { value: 'warning', label: 'เตือน' },
  { value: 'error', label: 'ผิดพลาด' },
]

const positionOptions = [
  { value: 'right', label: 'ด้านขวา' },
  { value: 'left', label: 'ด้านซ้าย' },
  { value: 'both', label: 'ทั้งสองด้าน' },
]

function showNotification() {
  const notification = {
    id: Date.now().toString(), // เพิ่ม ID
    title: notificationTitle.value || undefined,
    message: notificationMessage.value || 'ข้อความการแจ้งเตือน',
    type: notificationType.value,
    duration: notificationDuration.value,
    autoClose: autoClose.value && !requiresAcknowledgment.value, // ไม่ปิดอัตโนมัติถ้าต้องยืนยัน
    showTime: showTime.value,
    requiresAcknowledgment: requiresAcknowledgment.value, // เพิ่ม flag ต้องการยืนยัน
  }

  // แสดงการแจ้งเตือนตามตำแหน่งที่เลือก
  if (notificationPosition.value === 'right' || notificationPosition.value === 'both') {
    notifications.value.unshift(notification)
  }

  if (notificationPosition.value === 'left' || notificationPosition.value === 'both') {
    leftNotificationStore.addNotification(notification)
  }

  // ถ้าต้องการยืนยัน และเป็นการแจ้งเตือนด้านขวา จะใช้ notification store ด้วย
  if (
    requiresAcknowledgment.value &&
    (notificationPosition.value === 'right' || notificationPosition.value === 'both')
  ) {
    notificationStore.sendNotification({
      ...notification,
      requiresAcknowledgment: true,
    })
  }
}

function showMultipleNotifications() {
  // แสดงหลายรายการพร้อมกันเพื่อทดสอบ
  const types = ['info', 'success', 'warning', 'error']
  const messages = [
    'ระบบกำลังประมวลผล',
    'บันทึกข้อมูลสำเร็จ',
    'พื้นที่จัดเก็บเหลือน้อย',
    'เกิดข้อผิดพลาดในการเชื่อมต่อ',
  ]

  types.forEach((type, index) => {
    setTimeout(() => {
      const notification = {
        title: `การแจ้งเตือนประเภท ${type}`,
        message: messages[index],
        type: type,
        duration: notificationDuration.value,
        autoClose: autoClose.value,
        showTime: showTime.value,
      }

      // แสดงการแจ้งเตือนตามตำแหน่งที่เลือก
      if (notificationPosition.value === 'right' || notificationPosition.value === 'both') {
        notifications.value.unshift(notification)
      }

      if (notificationPosition.value === 'left' || notificationPosition.value === 'both') {
        leftNotificationStore.addNotification(notification)
      }
    }, index * 500)
  })
}

function removeNotification(index) {
  setTimeout(() => {
    notifications.value.splice(index, 1)
  }, 300)
}

// เพิ่มฟังก์ชันสำหรับยืนยันการแจ้งเตือน
function acknowledgeNotification(notificationId) {
  notificationStore.acknowledgeNotification(notificationId)
  // ลบออกจาก local notifications ด้วย
  const index = notifications.value.findIndex((n) => n.id === notificationId)
  if (index !== -1) {
    removeNotification(index)
  }
}
</script>

<style scoped>
.notification-examples {
  padding-bottom: 2rem;
}

.examples-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.notifications-container {
  display: flex;
  flex-direction: column;
  min-height: 300px;
}

.radio-group {
  display: flex;
  gap: 16px;
  margin-top: 4px;
}

.radio-group label {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.form-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-message {
  color: #94a3b8;
  text-align: center;
  padding: 20px;
}

.form-buttons {
  display: flex;
  gap: 12px;
}

@media (max-width: 768px) {
  .examples-container {
    grid-template-columns: 1fr;
  }
}
</style>
