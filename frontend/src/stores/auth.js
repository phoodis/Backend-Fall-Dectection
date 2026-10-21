import { defineStore } from 'pinia'
import { ref, computed, onMounted } from 'vue'
import authService from '@/services/authService'
import firebaseAuthService from '@/services/firebaseAuthService'

export const useAuthStore = defineStore('auth', () => {
    // State
    const user = ref(null)
    const isLoggedIn = ref(false)
    const isLoading = ref(false)
    const error = ref(null)
    const isInitialized = ref(false) // เพิ่มสถานะการเริ่มต้น

    // Clean up invalid localStorage data
    function cleanupInvalidStorageData() {
        const user = localStorage.getItem('user')
        const token = localStorage.getItem('authToken')

        if (user === 'undefined' || user === 'null') {
            localStorage.removeItem('user')
        }

        if (token === 'undefined' || token === 'null') {
            localStorage.removeItem('authToken')
        }
    }

    // Initialize auth state from localStorage
    async function initializeAuthState() {
        isLoading.value = true

        // Clean up any invalid data first
        cleanupInvalidStorageData()

        try {
            // Check for existing session in localStorage
            const storedUser = localStorage.getItem('user')
            const storedToken = localStorage.getItem('authToken')

            // Check if we have valid stored data (not null, not "undefined", not empty)
            if (storedUser && storedUser !== 'undefined' && storedUser !== 'null' &&
                storedToken && storedToken !== 'undefined' && storedToken !== 'null') {
                try {
                    const userData = JSON.parse(storedUser)

                    // Validate that userData is actually an object
                    if (userData && typeof userData === 'object' && userData.id) {
                        // First try online validation
                        try {
                            const { isLoggedIn: status, user: verifiedUser } = await authService.checkAuthStatus()

                            if (status && verifiedUser) {
                                user.value = verifiedUser
                                isLoggedIn.value = true
                                localStorage.setItem('user', JSON.stringify(verifiedUser))
                            } else {
                                // Token expired or invalid, clear localStorage
                                localStorage.removeItem('user')
                                localStorage.removeItem('authToken')
                                user.value = null
                                isLoggedIn.value = false
                            }
                        } catch (onlineError) {
                            // Fallback to offline validation
                            const { isLoggedIn: offlineStatus, user: offlineUser } = authService.checkAuthStatusOffline()

                            if (offlineStatus && offlineUser) {
                                user.value = offlineUser
                                isLoggedIn.value = true
                            } else {
                                localStorage.removeItem('user')
                                localStorage.removeItem('authToken')
                                user.value = null
                                isLoggedIn.value = false
                            }
                        }
                    } else {
                        localStorage.removeItem('user')
                        localStorage.removeItem('authToken')
                        user.value = null
                        isLoggedIn.value = false
                    }
                } catch (parseError) {
                    // Invalid stored data, clear localStorage
                    localStorage.removeItem('user')
                    localStorage.removeItem('authToken')
                    user.value = null
                    isLoggedIn.value = false
                }
            } else if (storedToken && storedToken !== 'undefined' && storedToken !== 'null') {
                // We have a token but no user data - try to validate and recover
                try {
                    const { isLoggedIn: status, user: verifiedUser } = await authService.checkAuthStatus()

                    if (status && verifiedUser) {
                        user.value = verifiedUser
                        isLoggedIn.value = true
                        localStorage.setItem('user', JSON.stringify(verifiedUser))
                    } else {
                        localStorage.removeItem('user')
                        localStorage.removeItem('authToken')
                        user.value = null
                        isLoggedIn.value = false
                    }
                } catch (recoveryError) {
                    localStorage.removeItem('user')
                    localStorage.removeItem('authToken')
                    user.value = null
                    isLoggedIn.value = false
                }
            } else {
                // No stored credentials or invalid data, clean up
                if (storedUser === 'undefined' || storedUser === 'null') {
                    localStorage.removeItem('user')
                }
                if (storedToken === 'undefined' || storedToken === 'null') {
                    localStorage.removeItem('authToken')
                }
                user.value = null
                isLoggedIn.value = false
            }
        } catch (error) {
            console.error('Error initializing auth state:', error)
            // Clear any stored data on initialization error
            localStorage.removeItem('user')
            localStorage.removeItem('authToken')
            user.value = null
            isLoggedIn.value = false
        } finally {
            isLoading.value = false
            isInitialized.value = true
        }
    }

    // Actions
    async function register(username, password, role = 'user') {
        isLoading.value = true
        error.value = null

        try {
            const result = await authService.register(username, password, role)
            return result
        } catch (err) {
            error.value = err.message || 'เกิดข้อผิดพลาดในการสมัครสมาชิก'
            throw error.value
        } finally {
            isLoading.value = false
        }
    }

    async function login(username, password) {
        isLoading.value = true
        error.value = null

        try {
            // เรียกใช้ service แทนโค้ด mock
            const result = await authService.login(username, password)

            // บันทึกข้อมูลผู้ใช้
            user.value = result.user
            isLoggedIn.value = true
            localStorage.setItem('user', JSON.stringify(result.user))

            return result.user
        } catch (err) {
            error.value = err.message || 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'
            throw error.value
        } finally {
            isLoading.value = false
        }
    }

    // เพิ่มฟังก์ชันเข้าสู่ระบบด้วย Google
    async function loginWithGoogle() {
        isLoading.value = true
        error.value = null

        try {
            const result = await firebaseAuthService.signInWithGoogle()

            // บันทึกข้อมูลผู้ใช้
            user.value = result.user
            isLoggedIn.value = true
            localStorage.setItem('user', JSON.stringify(result.user))
            localStorage.setItem('authToken', result.token)

            return result.user
        } catch (err) {
            error.value = err.message || 'เกิดข้อผิดพลาดในการเข้าสู่ระบบด้วย Google'
            throw error.value
        } finally {
            isLoading.value = false
        }
    }

    // เพิ่มฟังก์ชันเข้าสู่ระบบด้วย Google Redirect (สำหรับมือถือ)
    async function loginWithGoogleRedirect() {
        isLoading.value = true
        error.value = null

        try {
            await firebaseAuthService.signInWithGoogleRedirect()
        } catch (err) {
            error.value = err.message || 'เกิดข้อผิดพลาดในการเข้าสู่ระบบด้วย Google'
            isLoading.value = false
            throw error.value
        }
    }

    // ตรวจสอบผลลัพธ์จาก Google redirect
    async function checkGoogleRedirectResult() {
        try {
            const result = await firebaseAuthService.getRedirectResult()
            if (result) {
                user.value = result.user
                isLoggedIn.value = true
                localStorage.setItem('user', JSON.stringify(result.user))
                localStorage.setItem('authToken', result.token)
                return result.user
            }
            return null
        } catch (err) {
            error.value = err.message || 'เกิดข้อผิดพลาดในการเข้าสู่ระบบด้วย Google'
            return null
        }
    }

    async function logout() {
        isLoading.value = true
        try {
            // ออกจากระบบ Firebase ด้วย
            await firebaseAuthService.signOut()

            // เรียกใช้ service แทนโค้ดเดิม
            await authService.logout()
        } finally {
            // Clear state
            user.value = null
            isLoggedIn.value = false
            isLoading.value = false

            // Clear localStorage
            localStorage.removeItem('user')
            localStorage.removeItem('authToken')
        }
    }

    // ฟังก์ชันใหม่: ตรวจสอบสถานะการเข้าสู่ระบบ
    async function checkAuthStatus() {
        isLoading.value = true
        error.value = null

        try {
            const { isLoggedIn: status, user: userData } = await authService.checkAuthStatus()

            isLoggedIn.value = status
            user.value = userData

            if (userData) {
                localStorage.setItem('user', JSON.stringify(userData))
            } else {
                localStorage.removeItem('user')
            }

            return status
        } catch (err) {
            error.value = 'เกิดข้อผิดพลาดในการตรวจสอบสถานะการเข้าสู่ระบบ'
            isLoggedIn.value = false
            user.value = null
            localStorage.removeItem('user')
            return false
        } finally {
            isLoading.value = false
        }
    }

    // ติดตามสถานะ Firebase Auth
    function initFirebaseAuthListener() {
        firebaseAuthService.onAuthStateChanged(async(firebaseUser) => {
            if (firebaseUser && !user.value) {
                // ผู้ใช้เข้าสู่ระบบ Firebase แต่ยังไม่มีข้อมูลใน store
                try {
                    const userData = {
                        id: firebaseUser.uid,
                        email: firebaseUser.email,
                        name: firebaseUser.displayName,
                        avatar: firebaseUser.photoURL,
                        provider: 'google',
                        emailVerified: firebaseUser.emailVerified,
                    }

                    user.value = userData
                    isLoggedIn.value = true
                    localStorage.setItem('user', JSON.stringify(userData))

                    const token = await firebaseUser.getIdToken()
                    localStorage.setItem('authToken', token)
                } catch (err) {
                    console.error('Error handling Firebase auth state change:', err)
                }
            } else if (!firebaseUser && user.value && user.value.provider === 'google') {
                // ผู้ใช้ออกจากระบบ Firebase
                user.value = null
                isLoggedIn.value = false
                localStorage.removeItem('user')
                localStorage.removeItem('authToken')
            }
        })
    }

    // Helper functions สำหรับตรวจสอบ role
    const isAdmin = computed(() => {
        return user.value && user.value.role === 'admin'
    })

    const isUser = computed(() => {
        return user.value && user.value.role === 'user'
    })

    const hasRole = (role) => {
        return user.value && user.value.role === role
    }

    const canManageCameras = computed(() => {
        return isAdmin.value
    })

    const canManageUsers = computed(() => {
        return isAdmin.value
    })

    return {
        user,
        isLoggedIn,
        isLoading,
        error,
        isInitialized,
        isAdmin,
        isUser,
        hasRole,
        canManageCameras,
        canManageUsers,
        cleanupInvalidStorageData,
        initializeAuthState,
        register,
        login,
        loginWithGoogle,
        loginWithGoogleRedirect,
        checkGoogleRedirectResult,
        logout,
        checkAuthStatus,
        initFirebaseAuthListener,
    }
})
