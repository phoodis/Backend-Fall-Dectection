/**
 * Service สำหรับการสื่อสารกับ Backend API
 */
import { getApiBaseUrl, API_TIMEOUT } from '@/config/api'
import authService from './authService'

/**
 * ทำ fetch request พร้อมกำหนด timeout
 */
async function fetchWithTimeout(url, options = {}, timeout = API_TIMEOUT) {
    const controller = new AbortController()
    const id = setTimeout(() => controller.abort(), timeout)

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
        })

        if (!response.ok) {
            const error = new Error(`HTTP error! status: ${response.status}`)
            error.status = response.status
            throw error
        }

        return response
    } finally {
        clearTimeout(id)
    }
}

/**
 * ฟังก์ชั่นพื้นฐานสำหรับการส่ง request
 */
async function request(endpoint, method = 'GET', data = null, withAuth = true) {
    const url = `${getApiBaseUrl()}${endpoint}`
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
        },
    }

    // เพิ่ม Authorization header ถ้าต้องการ auth
    if (withAuth) {
        const token = await authService.getValidAccessToken()
        if (token) {
            options.headers['Authorization'] = `Bearer ${token}`
        }
    }

    // เพิ่ม body สำหรับ POST, PUT requests
    if (data && ['POST', 'PUT'].includes(method)) {
        options.body = JSON.stringify(data)
    }

    try {
        const response = await fetchWithTimeout(url, options)
        const result = await response.json().catch(() => ({}))
        return result
    } catch (error) {
        // จัดการกับ token หมดอายุ (401 Unauthorized)
        if (error.status === 401 && withAuth) {
            try {
                // ลอง refresh token
                const newToken = await authService.refreshToken()
                if (newToken) {
                    // ทำ request ใหม่อีกครั้งด้วย token ใหม่
                    options.headers['Authorization'] = `Bearer ${newToken}`
                    const retryResponse = await fetchWithTimeout(url, options)
                    const retryResult = await retryResponse.json().catch(() => ({}))
                    return retryResult
                }
            } catch (refreshError) {
                window.location.href = '/'
                throw refreshError
            }
        }

        throw error
    }
}

/**
 * Export API methods
 */
export default {
    // GET request
    get: async(endpoint, withAuth = true) => {
        return await request(endpoint, 'GET', null, withAuth)
    },

    // POST request
    post: async(endpoint, data, withAuth = true) => {
        return await request(endpoint, 'POST', data, withAuth)
    },

    // PUT request
    put: async(endpoint, data, withAuth = true) => {
        return await request(endpoint, 'PUT', data, withAuth)
    },

    // DELETE request
    delete: async(endpoint, withAuth = true) => {
        return await request(endpoint, 'DELETE', null, withAuth)
    },

    // Upload file
    upload: async(endpoint, file, onProgress, withAuth = true) => {
        const url = `${getApiBaseUrl()}${endpoint}`

        const formData = new FormData()
        formData.append('file', file)

        const xhr = new XMLHttpRequest()

        // สร้าง Promise สำหรับ XHR
        return new Promise(async (resolve, reject) => {
            xhr.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable && onProgress) {
                    const percentComplete = Math.round((event.loaded / event.total) * 100)
                    onProgress(percentComplete)
                }
            })

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        const response = JSON.parse(xhr.responseText)
                        resolve(response)
                    } catch (e) {
                        resolve({})
                    }
                } else {
                    reject({
                        status: xhr.status,
                        statusText: xhr.statusText,
                    })
                }
            })

            xhr.addEventListener('error', () => {
                reject({
                    status: xhr.status,
                    statusText: 'Network error occurred',
                })
            })

            xhr.addEventListener('abort', () => {
                reject({
                    status: xhr.status,
                    statusText: 'Request aborted',
                })
            })

            xhr.open('POST', url)

            // เพิ่ม Authorization header ถ้าต้องการ auth
            if (withAuth) {
                const token = await authService.getValidAccessToken()
                if (token) {
                    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
                }
            }

            xhr.send(formData)
        })
    },
}
