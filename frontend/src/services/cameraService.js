/**
 * Service จัดการกับ API เกี่ยวกับกล้อง
 * รองรับระบบ admin/user role
 */
import api from './api'
import { API_ENDPOINTS } from '@/config/api'

export default {
  /**
   * ดึงรายการกล้องทั้งหมด
   * Admin: เห็นกล้องทั้งหมดพร้อมข้อมูลเจ้าของ
   * User: เห็นเฉพาะกล้องของตัวเอง
   */
  getAllCameras: async () => {
    try {
      const response = await api.get(API_ENDPOINTS.CAMERAS.BASE)
      return response
    } catch (error) {
      console.error('Error fetching cameras:', error)
      throw new Error('ไม่สามารถดึงข้อมูลกล้องได้')
    }
  },

  /**
   * ดึงข้อมูลกล้องตาม ID
   * Admin: เห็นกล้องทุกตัว
   * User: เห็นเฉพาะกล้องของตัวเอง
   */
  getCameraById: async (cameraId) => {
    try {
      const response = await api.get(API_ENDPOINTS.CAMERAS.DETAIL(cameraId))
      return response
    } catch (error) {
      console.error(`Error fetching camera ${cameraId}:`, error)
      throw new Error('ไม่สามารถดึงข้อมูลกล้องได้')
    }
  },

  /**
   * ดึงสถานะการตรวจจับของกล้องตาม ID
   */
  getCameraStatus: async (cameraId) => {
    try {
      const response = await api.get(API_ENDPOINTS.CAMERAS.STATUS(cameraId))
      return response
    } catch (error) {
      console.error(`Error fetching camera status ${cameraId}:`, error)
      throw new Error('ไม่สามารถดึงสถานะกล้องได้')
    }
  },

  /**
   * เพิ่มกล้องใหม่ (Admin only)
   */
  addCamera: async (cameraData) => {
    try {
      // Set default values if not provided
      const defaultStartTime = "21:00"
      const defaultEndTime = "05:00"
      const defaultNotificationCooldown = 600
      const defaultAIConfidenceThreshold = 0.5

      // Prepare camera data as JSON
      const cameraPayload = {
        name: cameraData.name || 'Unnamed Camera',
        url: cameraData.url,
        room_name: cameraData.room_name || cameraData.name || 'Unnamed Room',
        detection_type: cameraData.detection_type || 'bed_exit',
        owner_id: cameraData.owner_id, // เพิ่ม owner_id
        alert_start_time: cameraData.alert_start_time !== undefined ? cameraData.alert_start_time : defaultStartTime,
        alert_end_time: cameraData.alert_end_time !== undefined ? cameraData.alert_end_time : defaultEndTime,
        notification_cooldown: cameraData.notification_cooldown !== undefined ? cameraData.notification_cooldown : defaultNotificationCooldown,
        ai_confidence_threshold: cameraData.ai_confidence_threshold !== undefined ? cameraData.ai_confidence_threshold : defaultAIConfidenceThreshold,
      }

      const response = await api.post(API_ENDPOINTS.CAMERAS.BASE, cameraPayload)
      const cameraId = response.id

      // เริ่ม monitor
      const monitorResult = await api.post(API_ENDPOINTS.CAMERAS.START(cameraId))

      // ส่งข้อมูลกล้อง + สถานะ monitor กลับ
      return { camera: response, monitor: monitorResult }
    } catch (error) {
      console.error('Error adding camera:', error)
      throw new Error('ไม่สามารถเพิ่มกล้องได้')
    }
  },

  /**
   * อัปเดตข้อมูลกล้อง (Admin only)
   */
  updateCamera: async (cameraId, cameraData) => {
    try {
      // ดึงข้อมูลกล้องเดิมมาเปรียบเทียบ url และ detection_type
      const oldCamera = await api.get(API_ENDPOINTS.CAMERAS.DETAIL(cameraId))

      let monitorStopped = null
      let monitorStarted = null

      // ตรวจสอบว่า url หรือ detection_type เปลี่ยนหรือไม่
      const urlChanged = oldCamera.url !== cameraData.url
      const detectionTypeChanged = oldCamera.detection_type !== cameraData.detection_type
      const needsMonitorRestart = urlChanged || detectionTypeChanged

      // ถ้า url หรือ detection_type เปลี่ยน ให้หยุด monitor เดิมก่อน
      if (needsMonitorRestart) {
        try {
          monitorStopped = await api.post(API_ENDPOINTS.CAMERAS.STOP(cameraId))
        } catch (e) {
          monitorStopped = { error: 'Invalid stop_monitor response' }
        }
      }

      // อัปเดตข้อมูลกล้อง
      const response = await api.put(API_ENDPOINTS.CAMERAS.DETAIL(cameraId), cameraData)

      // ถ้า url หรือ detection_type เปลี่ยน ให้ start monitor ใหม่
      if (needsMonitorRestart) {
        try {
          await api.post(API_ENDPOINTS.CAMERAS.STOP(cameraId))
          monitorStarted = await api.post(API_ENDPOINTS.CAMERAS.START(cameraId))
        } catch (e) {
          monitorStarted = { error: 'Invalid start_monitor response' }
        }
      }

      // ส่ง response กลับพร้อมข้อมูลการเปลี่ยนแปลง
      return {
        camera: response,
        monitorStopped,
        monitorStarted,
        urlChanged,
        detectionTypeChanged,
        monitorRestarted: needsMonitorRestart
      }
    } catch (error) {
      console.error(`Error updating camera ${cameraId}:`, error)
      throw new Error('ไม่สามารถอัปเดตกล้องได้')
    }
  },

  /**
   * ลบกล้อง (Admin only)
   */
  deleteCamera: async (cameraId) => {
    try {
      // หยุด monitor ก่อนลบกล้อง
      let monitorStopped = null
      try {
        monitorStopped = await api.post(API_ENDPOINTS.CAMERAS.STOP(cameraId))
      } catch (e) {
        monitorStopped = { error: 'Invalid stop_monitor response' }
      }

      // ลบกล้อง
      await api.delete(API_ENDPOINTS.CAMERAS.DETAIL(cameraId))
      return { success: true, monitorStopped }
    } catch (error) {
      console.error(`Error deleting camera ${cameraId}:`, error)
      throw new Error('ไม่สามารถลบกล้องได้')
    }
  },

  /**
   * ดึงรายชื่อไฟล์วิดีโอทดสอบที่วางไว้ในโฟลเดอร์วิดีโอของ backend (TEST_VIDEO_DIR)
   * ใช้แทนการให้ผู้ใช้พิมพ์ path ไฟล์เอง (ป้องกันการใส่ path ของเครื่อง Windows ผิด)
   */
  getTestVideos: async () => {
    try {
      const response = await api.get(API_ENDPOINTS.CAMERAS.TEST_VIDEOS)
      return response
    } catch (error) {
      console.error('Error fetching test videos:', error)
      throw new Error('ไม่สามารถดึงรายชื่อไฟล์วิดีโอทดสอบได้')
    }
  },

  /**
   * เริ่มการตรวจจับกล้อง
   */
  startCamera: async (cameraId) => {
    try {
      const response = await api.post(API_ENDPOINTS.CAMERAS.START(cameraId))
      return response
    } catch (error) {
      console.error(`Error starting camera ${cameraId}:`, error)
      throw new Error('ไม่สามารถเริ่มการตรวจจับกล้องได้')
    }
  },

  /**
   * หยุดการตรวจจับกล้อง
   */
  stopCamera: async (cameraId) => {
    try {
      const response = await api.post(API_ENDPOINTS.CAMERAS.STOP(cameraId))
      return response
    } catch (error) {
      console.error(`Error stopping camera ${cameraId}:`, error)
      throw new Error('ไม่สามารถหยุดการตรวจจับกล้องได้')
    }
  },
}
