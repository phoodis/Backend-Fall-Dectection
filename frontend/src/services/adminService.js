/**
 * Service จัดการกับ API เกี่ยวกับการจัดการผู้ใช้และระบบ (Admin only)
 */
import api from './api'
import { API_ENDPOINTS } from '@/config/api'

export default {
  /**
   * ดึงรายการผู้ใช้ทั้งหมด (Admin only)
   */
  getUsers: async function() {
    try {
      const response = await api.get(API_ENDPOINTS.ADMIN.USERS)
      return response
    } catch (error) {
      console.error('Failed to fetch users:', error)
      throw new Error('ไม่สามารถดึงข้อมูลผู้ใช้ได้')
    }
  },

  /**
   * สร้างผู้ใช้ใหม่ (Admin only)
   */
  createUser: async function(userData) {
    try {
      const response = await api.post(API_ENDPOINTS.ADMIN.USERS, userData)
      return response
    } catch (error) {
      console.error('Failed to create user:', error)

      // แยกประเภท error ตาม HTTP status
      if (error.status === 409) {
        throw new Error('ชื่อผู้ใช้นี้มีอยู่แล้ว')
      } else if (error.status === 400) {
        throw new Error('ข้อมูลที่ส่งมาไม่ถูกต้อง')
      }

      throw new Error('ไม่สามารถสร้างผู้ใช้ได้')
    }
  },

  /**
   * อัพเดทข้อมูลผู้ใช้ (Admin only)
   */
  updateUser: async function(userId, userData) {
    try {
      const response = await api.put(API_ENDPOINTS.ADMIN.USER_DETAIL(userId), userData)
      return response
    } catch (error) {
      console.error('Failed to update user:', error)

      if (error.status === 400) {
        throw new Error('ไม่สามารถเปลี่ยนบทบาทของตนเองได้')
      } else if (error.status === 404) {
        throw new Error('ไม่พบผู้ใช้นี้')
      }

      throw new Error('ไม่สามารถอัพเดทข้อมูลผู้ใช้ได้')
    }
  },

  /**
   * ลบผู้ใช้ (Admin only)
   */
  deleteUser: async function(userId) {
    try {
      const response = await api.delete(API_ENDPOINTS.ADMIN.USER_DETAIL(userId))
      return response
    } catch (error) {
      console.error('Failed to delete user:', error)

      if (error.status === 400) {
        throw new Error('ไม่สามารถลบบัญชีของตนเองได้')
      } else if (error.status === 404) {
        throw new Error('ไม่พบผู้ใช้นี้')
      }

      throw new Error('ไม่สามารถลบผู้ใช้ได้')
    }
  },

  /**
   * ดึงข้อมูล dashboard สำหรับ admin
   */
  getDashboard: async function() {
    try {
      const response = await api.get(API_ENDPOINTS.ADMIN.DASHBOARD)
      return response
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error)
      throw new Error('ไม่สามารถดึงข้อมูล dashboard ได้')
    }
  },
}
