import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useLeftNotificationStore = defineStore('leftNotification', () => {
  // State
  const notifications = ref([])
  const maxNotifications = ref(5) // จำนวนการแจ้งเตือนสูงสุดที่จะแสดงในเวลาเดียวกัน

  // Actions
  function addNotification(notification) {
    // ให้แน่ใจว่า notification มี id และ timestamp
    const newNotification = {
      id: Date.now().toString(),
      timestamp: new Date(),
      ...notification,
    }

    // เพิ่มการแจ้งเตือนใหม่ที่ด้านบนของรายการ
    notifications.value.unshift(newNotification)

    // ตัดการแจ้งเตือนเก่าออกหากเกินจำนวนที่กำหนด
    if (notifications.value.length > maxNotifications.value) {
      notifications.value.pop()
    }

    // ตั้งเวลาลบการแจ้งเตือนโดยอัตโนมัติหากมีการกำหนด duration
    if (notification.duration) {
      setTimeout(() => {
        removeNotification(newNotification.id)
      }, notification.duration)
    }

    return newNotification.id
  }

  function removeNotification(id) {
    const index = notifications.value.findIndex((n) => n.id === id)
    if (index !== -1) {
      notifications.value.splice(index, 1)
    }
  }

  function clearAllNotifications() {
    notifications.value = []
  }

  return {
    notifications,
    maxNotifications,
    addNotification,
    removeNotification,
    clearAllNotifications,
  }
})
