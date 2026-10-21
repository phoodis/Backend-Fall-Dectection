import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useNotificationStore = defineStore('notification', () => {
  const notifications = ref([])
  const cooldownPeriod = ref(60000) // 1 นาทีสำหรับระยะเวลาคูลดาวน์ระหว่างการแจ้งเตือน
  const lastNotificationTime = ref(0)
  const pendingNotifications = ref([]) // เพิ่มตัวแปรสำหรับเก็บการแจ้งเตือนที่ยังไม่ได้รับการยืนยัน
  const reminderInterval = ref(120000) // 2 นาทีสำหรับระยะเวลาในการแจ้งเตือนซ้ำ

  // ตัวแปรเก็บ timer ID สำหรับการแจ้งเตือนซ้ำ
  const reminderTimers = ref({})

  // ส่งการแจ้งเตือนถ้าไม่อยู่ในช่วงคูลดาวน์
  function sendNotification(notification) {
    const now = Date.now()
    const notificationWithId = {
      ...notification,
      id: 'notification_' + now,
      timestamp: notification.timestamp || now,
      acknowledged: false,
      requiresAcknowledgment: notification.requiresAcknowledgment || false,
    }

    if (now - lastNotificationTime.value > cooldownPeriod.value) {
      notifications.value.unshift(notificationWithId) // เพิ่มที่ต้นอาร์เรย์
      lastNotificationTime.value = now

      // จำกัดจำนวนการแจ้งเตือนที่เก็บไว้
      if (notifications.value.length > 10) {
        notifications.value.pop() // ลบการแจ้งเตือนที่เก่าที่สุด
      }

      // ถ้าต้องการยืนยัน ให้ตั้งเวลาแจ้งเตือนซ้ำและเก็บในรายการรอการยืนยัน
      if (notificationWithId.requiresAcknowledgment) {
        pendingNotifications.value.push(notificationWithId)
        setReminderTimer(notificationWithId)
      }

      // บันทึกการแจ้งเตือน
      logAlert(notificationWithId)

      return true
    }

    return false // อยู่ในช่วงคูลดาวน์
  }

  // ตั้งเวลาสำหรับแจ้งเตือนซ้ำ
  function setReminderTimer(notification) {
    reminderTimers.value[notification.id] = setTimeout(() => {
      // ตรวจสอบว่าการแจ้งเตือนนี้ยังอยู่ในรายการรอการยืนยันหรือไม่
      if (pendingNotifications.value.some((n) => n.id === notification.id)) {
        // สร้างการแจ้งเตือนซ้ำ
        const reminderNotification = {
          ...notification,
          title: `แจ้งเตือนซ้ำ: ${notification.title}`,
          timestamp: Date.now(),
        }

        // เพิ่มการแจ้งเตือนซ้ำที่ด้านบนสุดของรายการ
        notifications.value.unshift(reminderNotification)

        // ตั้งเวลาแจ้งเตือนซ้ำอีกครั้ง
        setReminderTimer(notification)
      }
    }, reminderInterval.value)
  }

  // ยืนยันการรับทราบการแจ้งเตือน
  function acknowledgeNotification(notificationId) {
    // หา index ของการแจ้งเตือนใน notifications
    const index = notifications.value.findIndex((n) => n.id === notificationId)
    if (index !== -1) {
      notifications.value[index].acknowledged = true
    }

    // ลบออกจาก pendingNotifications
    const pendingIndex = pendingNotifications.value.findIndex((n) => n.id === notificationId)
    if (pendingIndex !== -1) {
      pendingNotifications.value.splice(pendingIndex, 1)
    }

    // ยกเลิก timer สำหรับการแจ้งเตือนซ้ำ
    if (reminderTimers.value[notificationId]) {
      clearTimeout(reminderTimers.value[notificationId])
      delete reminderTimers.value[notificationId]
    }
  }

  // บันทึกการแจ้งเตือนไปยังคอนโซล (ในแอปพลิเคชันจริง นี่จะเป็นการเรียก API)
  function logAlert(notification) {
    // console.log('บันทึกการแจ้งเตือน:', notification)
    // ในแอปพลิเคชันจริง คุณจะส่งข้อมูลนี้ไปยังบริการแบ็กเอนด์
  }

  // ตั้งค่าระยะเวลาคูลดาวน์เป็นมิลลิวินาที
  function setCooldownPeriod(milliseconds) {
    cooldownPeriod.value = milliseconds
  }

  // ตั้งค่าระยะเวลาในการแจ้งเตือนซ้ำเป็นมิลลิวินาที
  function setReminderInterval(milliseconds) {
    reminderInterval.value = milliseconds
  }

  // ล้างการแจ้งเตือนทั้งหมด
  function clearNotifications() {
    notifications.value = []
    pendingNotifications.value = []

    // ยกเลิก timers ทั้งหมด
    Object.values(reminderTimers.value).forEach((timer) => {
      clearTimeout(timer)
    })
    reminderTimers.value = {}
  }

  return {
    notifications,
    cooldownPeriod,
    reminderInterval,
    pendingNotifications,
    sendNotification,
    acknowledgeNotification,
    setCooldownPeriod,
    setReminderInterval,
    clearNotifications,
  }
})
