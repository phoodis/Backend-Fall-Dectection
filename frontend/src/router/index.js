import { createRouter, createWebHistory } from 'vue-router'
import StartView from '../views/StartView.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
    history: createWebHistory(
        import.meta.env.BASE_URL),
    routes: [{
            path: '/',
            name: 'start',
            component: StartView,
        },
        {
            path: '/dashboard',
            name: 'dashboard',
            component: () =>
                import ('../views/DashboardView.vue'),
            meta: { requiresAuth: true },
        },
        {
            path: '/camera',
            name: 'camera',
            component: () =>
                import ('../views/CameraManagementView.vue'),
            meta: { requiresAuth: true, requiresAdmin: true },
        },
        {
            path: '/users',
            name: 'users',
            component: () =>
                import ('../views/UserManagementView.vue'),
            meta: { requiresAuth: true, requiresAdmin: true },
        },
        {
            path: '/monitor',
            name: 'monitor',
            component: () =>
                import ('../views/MonitorView.vue'),
            meta: { requiresAuth: true },
        },
        {
            path: '/notification-settings',
            name: 'notification-settings',
            component: () =>
                import ('../views/NotificationSettingsView.vue'),
            meta: { requiresAuth: true },
        },
        {
            path: '/system-logs',
            name: 'system-logs',
            component: () =>
                import ('../views/SystemLogView.vue'),
            meta: { requiresAuth: true, requiresAdmin: true },
        },
        {
            path: '/about',
            name: 'about',
            component: () =>
                import ('../views/AboutView.vue'),
            meta: { requiresAuth: true },
        },
        {
            path: '/thai-frat-list',
            name: 'thai-frat-list',
            component: () =>
                import ('../views/ThaiFratListView.vue'),
        },
        {
            path: '/thai-frat-form',
            name: 'thai-frat-form',
            component: () =>
                import ('../views/ThaiFratFormView.vue'),
        },
        {
            path: '/thai-frat-detail/:id',
            name: 'ThaiFratDetail',
            component: () =>
                import ('../views/ThaiFratDetailView.vue'),
            props: true,
        },
        // เพิ่มเส้นทางสำหรับหน้า 404
        {
            path: '/:pathMatch(.*)*',
            name: 'not-found',
            component: () =>
                import ('../views/NotFoundView.vue'),
        },
    ],
})

// ตรวจสอบการล็อกอินก่อนเข้าหน้าที่ต้องการสิทธิ์
router.beforeEach(async (to, from, next) => {
    const authStore = useAuthStore()

    // รอให้ auth state ถูกเริ่มต้นก่อน
    if (!authStore.isInitialized) {
        await authStore.initializeAuthState()
    }

    // ตรวจสอบการเข้าสู่ระบบ
    if (to.meta.requiresAuth && !authStore.isLoggedIn) {
        next('/')
        return
    }

    // ตรวจสอบสิทธิ์ admin
    if (to.meta.requiresAdmin && !authStore.isAdmin) {
        // ถ้าไม่ใช่ admin ให้ redirect ไป dashboard
        next('/dashboard')
        return
    }

    if (to.path === '/' && authStore.isLoggedIn) {
        // ถ้าเข้าสู่ระบบแล้วและพยายามไปหน้า start ให้ redirect ไป dashboard
        next('/dashboard')
    } else {
        next()
    }
})

export default router
