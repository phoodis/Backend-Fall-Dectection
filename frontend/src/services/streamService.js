/**
 * Service จัดการ Video Streaming จาก backend
 */
import { getApiBaseUrl, API_ENDPOINTS } from '@/config/api'

// Helper to get auth token from localStorage
function getAuthToken() {
    return localStorage.getItem('authToken')
}

export default {
  /**
   * สร้าง URL สำหรับ MJPEG stream จากกล้อง
   * overlay=true จะให้ backend วาดกรอบ+เส้น skeleton จากโมเดล pose ทับภาพ
   * (ใช้โมเดลจริงอีกครั้งเพื่อวาด จึงหน่วงกว่าโหมดปกติที่ส่งวิดีโอดิบ)
   */
  getCameraStreamUrl: async (cameraId, overlay = false) => {
    // The live view is an <img>, which cannot send an Authorization header, so it carries a
    // short-lived media token instead: valid for 60 s to START a view of this one camera, and
    // useless as a login anywhere else. This used to append the user's full login token as
    // ?token=, which put a credential for every API into server logs and browser history --
    // and the backend never read it. See app/services/media_token.py.
    // Returns { url, maxViewSeconds } or null.
    try {
      const baseUrl = getApiBaseUrl()
      if (!baseUrl) throw new Error('API base URL is not defined')
      const res = await fetch(`${baseUrl}${API_ENDPOINTS.STREAM.MEDIA_TOKEN(cameraId)}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getAuthToken()}` },
        cache: 'no-store'
      })
      if (!res.ok) throw new Error(`media token refused (HTTP ${res.status})`)
      const body = await res.json()
      // the second argument matters when VITE_API_BASE_URL is the relative `/api` (dev-server proxy)
      const url = new URL(`${baseUrl}${API_ENDPOINTS.STREAM.CAMERA(cameraId)}`, window.location.href)
      url.searchParams.append('t', body.token)
      if (overlay) url.searchParams.append('overlay', '1')
      return {
        url: url.toString(),
        maxViewSeconds: body.max_view_seconds || 600,
        // false when the server does not draw the skeleton (STREAM_OVERLAY_ENABLED) and will ignore overlay=1
        overlayAvailable: body.overlay_available !== false
      }
    } catch (error) {
      console.error(`Error creating camera stream URL for camera ${cameraId}:`, error)
      return null
    }
  },

  /**
   * เริ่ม stream กล้อง
   */
  startCameraStream: async (cameraId) => {
  try {
    const token = getAuthToken()

    const response = await fetch(
      `${getApiBaseUrl()}${API_ENDPOINTS.STREAM.START(cameraId)}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      }
    )

    const data = await response.json().catch(() => null)

    if (!response.ok) {
      console.error('❌ Backend response error:', data)

      throw new Error(
        data?.message ||
        data?.error ||
        `HTTP ${response.status}`
      )
    }

    return data

  } catch (error) {
    console.error(`🔥 Error starting camera stream ${cameraId}:`, error)
    throw error
  }
},

  /**
   * หยุด stream กล้อง
   */
  stopCameraStream: async (cameraId) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.STREAM.STOP(cameraId)}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      })
      if (!response.ok) {
        throw new Error('Failed to stop camera stream')
      }
      const data = await response.json()
      return data
    } catch (error) {
      console.error(`Error stopping camera stream ${cameraId}:`, error)
      throw error
    }
  },

  /**
   * ดึงสถานะ stream ของกล้อง
   */
  getCameraStreamStatus: async (cameraId) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.STREAM.STATUS(cameraId)}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      })
      if (!response.ok) {
        throw new Error('Failed to get camera stream status')
      }
      const data = await response.json()
      return data
    } catch (error) {
      console.error(`Error getting camera stream status ${cameraId}:`, error)
      throw error
    }
  },

  /**
   * ดึงสถิติ stream ทั้งหมด
   */
  getStreamStats: async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.STREAM.STATS}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      })
      if (!response.ok) {
        throw new Error('Failed to get stream stats')
      }
      const data = await response.json()
      return data
    } catch (error) {
      console.error('Error getting stream stats:', error)
      throw error
    }
  },

  /**
   * ทดสอบการเชื่อมต่อกล้อง
   */
  testCameraStream: async (cameraId) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.STREAM.TEST(cameraId)}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      })
      if (!response.ok) {
        throw new Error('Failed to test camera stream')
      }
      const data = await response.json()
      return data
    } catch (error) {
      console.error(`Error testing camera stream ${cameraId}:`, error)
      throw error
    }
  },

  /**
   * ทำความสะอาด streams ที่ไม่ใช้งาน
   */
  cleanupStreams: async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.STREAM.CLEANUP}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
      })
      if (!response.ok) {
        throw new Error('Failed to cleanup streams')
      }
      const data = await response.json()
      return data
    } catch (error) {
      console.error('Error cleaning up streams:', error)
      throw error
    }
  },
}
