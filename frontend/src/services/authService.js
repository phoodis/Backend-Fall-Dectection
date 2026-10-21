/**
 * Service จัดการกับ API เกี่ยวกับการยืนยันตัวตนและผู้ใช้
 */
import { getApiBaseUrl, API_ENDPOINTS } from '@/config/api'

// ตัวแปรสำหรับป้องกันการ refresh token หลายครั้งพร้อมกัน
let refreshPromise = null
let isRefreshing = false

export default {
  /**
   * สมัครสมาชิก
   */
  register: async function(username, password, role = 'user') {
    try {
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.REGISTER}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password, role }),
      })
      
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.error || 'เกิดข้อผิดพลาดในการสมัครสมาชิก')
      }
      
      const data = await response.json()
      return data
    } catch (error) {
      throw new Error(error.message || 'เกิดข้อผิดพลาดในการสมัครสมาชิก')
    }
  },

  /**
   * เข้าสู่ระบบ
   */
  login: async function(username, password) {
    try {
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.LOGIN}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.message || 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')
      }
      const data = await response.json()

      // เก็บ access token, refresh token และ user ลง localStorage
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      localStorage.setItem('user', JSON.stringify(data.user))

      // Keep backward compatibility
      localStorage.setItem('authToken', data.access_token)

      return data
    } catch (error) {
      throw new Error(error.message || 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')
    }
  },

  /**
   * ออกจากระบบ
   */
  logout: async function() {
    try {
      const accessToken = localStorage.getItem('access_token')

      // เรียก API logout เพื่อ blacklist token ที่ backend
      if (accessToken) {
        try {
          await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.LOGOUT}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${accessToken}`
            },
          })
        } catch (error) {
          console.warn('Logout API call failed:', error)
        }
      }

      // ล้าง tokens และข้อมูลผู้ใช้
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')

    } catch (error) {
      console.warn('Logout failed', error)
    }
  },

  /**
   * ออกจากระบบทุกอุปกรณ์
   */
  logoutAll: async function() {
    try {
      const accessToken = localStorage.getItem('access_token')

      if (accessToken) {
        await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.LOGOUT_ALL}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${accessToken}`
          },
        })
      }

      // ล้าง tokens และข้อมูลผู้ใช้
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')

    } catch (error) {
      console.warn('Logout all failed', error)
    }
  },

  /**
   * ตรวจสอบว่า token หมดอายุหรือไม่
   */
  isTokenExpired: function(token) {
    if (!token) return true

    try {
      const tokenParts = token.split('.')
      if (tokenParts.length !== 3) return true

      const payload = JSON.parse(atob(tokenParts[1]))
      const currentTime = Math.floor(Date.now() / 1000)

      // เช็คว่าจะหมดอายุในอีก 5 นาที (300 วินาที)
      return payload.exp && (payload.exp - currentTime) < 300
    } catch (error) {
      return true
    }
  },

  /**
   * Refresh access token
   */
  refreshToken: async function() {
    // ป้องกันการ refresh หลายครั้งพร้อมกัน
    if (isRefreshing) {
      return refreshPromise
    }

    isRefreshing = true
    refreshPromise = new Promise(async (resolve, reject) => {
      try {
        const refreshToken = localStorage.getItem('refresh_token')

        if (!refreshToken) {
          throw new Error('No refresh token available')
        }

        const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.REFRESH}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${refreshToken}`
          },
        })

        if (!response.ok) {
          throw new Error('Token refresh failed')
        }

        const data = await response.json()

        // อัพเดท access token ใหม่
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('authToken', data.access_token) // backward compatibility

        // อัพเดทข้อมูลผู้ใช้ถ้ามี
        if (data.user) {
          localStorage.setItem('user', JSON.stringify(data.user))
        }

        resolve(data.access_token)
      } catch (error) {
        // ล้าง tokens ถ้า refresh ไม่สำเร็จ
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('authToken')
        localStorage.removeItem('user')

        reject(error)
      } finally {
        isRefreshing = false
        refreshPromise = null
      }
    })

    return refreshPromise
  },

  /**
   * ดึง access token ที่ถูกต้อง (refresh อัตโนมัติถ้าจำเป็น)
   */
  getValidAccessToken: async function() {
    let accessToken = localStorage.getItem('access_token')

    if (this.isTokenExpired(accessToken)) {
      try {
        accessToken = await this.refreshToken()
      } catch (error) {
        return null
      }
    }

    return accessToken
  },

  /**
   * ตรวจสอบสถานะการเข้าสู่ระบบ (แบบ offline-friendly)
   */
  checkAuthStatusOffline: function() {
    try {
      const accessToken = localStorage.getItem('access_token')
      const refreshToken = localStorage.getItem('refresh_token')
      const storedUser = localStorage.getItem('user')

      // Check for invalid or missing data
      if ((!accessToken && !refreshToken) || !storedUser ||
          storedUser === 'undefined' || storedUser === 'null') {
        return { isLoggedIn: false, user: null }
      }

      // Parse user data
      let userData
      try {
        userData = JSON.parse(storedUser)

        // Validate user data structure
        if (!userData || typeof userData !== 'object' || !userData.id) {
          return { isLoggedIn: false, user: null }
        }
      } catch (parseError) {
        return { isLoggedIn: false, user: null }
      }

      // ถ้ามี refresh token ให้ถือว่า login อยู่ (จะ refresh access token ตอนใช้งาน)
      if (refreshToken && refreshToken !== 'undefined' && refreshToken !== 'null') {
        return { isLoggedIn: true, user: userData }
      }

      // ถ้ามีแค่ access token ให้เช็คว่าหมดอายุหรือไม่
      if (accessToken && !this.isTokenExpired(accessToken)) {
        return { isLoggedIn: true, user: userData }
      }

      return { isLoggedIn: false, user: null }
    } catch (error) {
      console.error('Offline auth check failed:', error)
      return { isLoggedIn: false, user: null }
    }
  },

  /**
   * ตรวจสอบสถานะการเข้าสู่ระบบ
   */
  checkAuthStatus: async function() {
    try {
      // ตรวจสอบว่ามี token อยู่หรือไม่
      const accessToken = localStorage.getItem('access_token')
      const refreshToken = localStorage.getItem('refresh_token')
      const storedUser = localStorage.getItem('user')

      if ((!accessToken && !refreshToken)) {
        return { isLoggedIn: false, user: null }
      }

      // ถ้า access token หมดอายุ ให้ลอง refresh
      let validToken = accessToken
      if (this.isTokenExpired(accessToken)) {
        try {
          validToken = await this.refreshToken()
        } catch (refreshError) {
          return { isLoggedIn: false, user: null }
        }
      }

      // ลองใช้ token เรียก API เพื่อตรวจสอบว่ายังใช้ได้อยู่หรือไม่
      const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.AUTH.VERIFY}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${validToken}`
        },
      })

      if (response.ok) {
        const verifyData = await response.json()

        // อัพเดทข้อมูลผู้ใช้จาก verify response
        if (verifyData.user) {
          localStorage.setItem('user', JSON.stringify(verifyData.user))
          return { isLoggedIn: true, user: verifyData.user }
        }

        // ถ้าไม่มีข้อมูลผู้ใช้จาก verify ให้ใช้ที่เก็บไว้
        if (storedUser && storedUser !== 'undefined' && storedUser !== 'null') {
          try {
            const userData = JSON.parse(storedUser)
            if (userData && userData.id) {
              return { isLoggedIn: true, user: userData }
            }
          } catch (parseError) {
            // Silent fallback failure
          }
        }

        // สร้าง fallback user object
        const fallbackUser = {
          id: 'user_' + Date.now(),
          name: 'User',
          username: 'user'
        }
        return { isLoggedIn: true, user: fallbackUser }
      } else {
        // Token ไม่ถูกต้อง ลบข้อมูลทั้งหมด
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('authToken')
        localStorage.removeItem('user')
        return { isLoggedIn: false, user: null }
      }
    } catch (error) {
      console.error('Auth status check failed:', error)

      // For network errors, try to use stored user data as fallback
      const storedUser = localStorage.getItem('user')
      const refreshToken = localStorage.getItem('refresh_token')

      if (refreshToken && storedUser && storedUser !== 'undefined' && storedUser !== 'null') {
        try {
          const userData = JSON.parse(storedUser)
          if (userData && userData.id) {
            return { isLoggedIn: true, user: userData }
          }
        } catch (parseError) {
          // Silent fallback failure
        }
      }

      // If all else fails, clear session
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')
      return { isLoggedIn: false, user: null }
    }
  },
}
