/**
 * ไฟล์กำหนดค่า API สำหรับการเชื่อมต่อกับ Backend
 */


// ฟังก์ชันสำหรับดึง Base URL จาก backend store
import { useBackendStore } from '@/stores/backend'
export function getApiBaseUrl() {
    // ถ้า store ยังไม่ถูกสร้าง (เช่นนอก context Vue) ให้ fallback เป็น env
    try {
        const { selectedBackend } = useBackendStore()
        if (selectedBackend && selectedBackend.url) {
            // return selectedBackend.url
            return import.meta.env.VITE_API_BASE_URL
        }
    } catch (e) {}
    return import.meta.env.VITE_API_BASE_URL
}

// Timeout สำหรับ request (ms)
export const API_TIMEOUT = 15000

// Endpoints
export const API_ENDPOINTS = {
  // ผู้ใช้งาน
  AUTH: {
    LOGIN: '/auth/login',
    LOGOUT: '/auth/logout',
    LOGOUT_ALL: '/auth/logout-all',
    REFRESH: '/auth/refresh',
    VERIFY: '/auth/verify',
    REGISTER: '/auth/register',
  },

  // Admin Management
  ADMIN: {
    USERS: '/admin/users',
    USER_DETAIL: (id) => `/admin/users/${id}`,
    DASHBOARD: '/admin/dashboard',
  },

  // กล้อง
  CAMERAS: {
    BASE: '/cameras',
    DETAIL: (id) => `/cameras/${id}`,
    STATUS: (id) => `/cameras/${id}/status`,
    START: (id) => `/cameras/${id}/start`,
    STOP: (id) => `/cameras/${id}/stop`,
    TEST_VIDEOS: '/cameras/test-videos',
  },

  // video streaming
  STREAM: {
    CAMERA: (id) => `/stream/camera/${id}`,
    MEDIA_TOKEN: (id) => `/stream/camera/${id}/media-token`,
    START: (id) => `/stream/camera/${id}/start`,
    STOP: (id) => `/stream/camera/${id}/stop`,
    STATUS: (id) => `/stream/camera/${id}/status`,
    STATS: '/stream/stats',
    CLEANUP: '/stream/cleanup',
    TEST: (id) => `/stream/camera/${id}/test`,
  },

  // log
  LOG: {
    BASE: '/detection-logs',
    DETAIL: (id) => `/detection-logs/${id}`,
  },

  // notifications
  NOTIFICATIONS: {
    BASE: '/detection-logs/notifications',
    DETAIL: (id) => `/detection-logs/notifications/${id}`,
    ACKNOWLEDGE: (id) => `/detection-logs/notifications/${id}/acknowledge`,
  },

  // system logs
  SYSTEM_LOGS: {
    BASE: '/system-logs',
    LEVELS: '/system-logs/levels',
    COMPONENTS: '/system-logs/components',
  },

  // line
  LINE: {
    SETTINGS: '/line/settings',
    TEST: '/line/test',
  },

  // assignments
  ASSIGNMENTS: {
    BASE: '/thai-frat/assessments',
    DETAIL: (id) => `/thai-frat/assessments/${id}`,
    SHARE: (id) => `/thai-frat/assessments/${id}/share`,
    DELETESHARE: (id, username) => `/thai-frat/assessments/${id}/share/${username}`,
    OPTION: `/thai-frat/question-options`,
  },
}

// HTTP status codes ที่ใช้บ่อย
export const HTTP_STATUS = {
    OK: 200,
    CREATED: 201,
    BAD_REQUEST: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    INTERNAL_SERVER_ERROR: 500,
}
