import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider } from 'firebase/auth'
import { getAnalytics, isSupported as isAnalyticsSupported } from 'firebase/analytics'

const firebaseConfig = {
    // คุณต้องเพิ่มค่าเหล่านี้จากโปรเจ็ค Firebase ของคุณ
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID,
    measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID
}

// Firebase is optional (only backs the "sign in with Google" flow and analytics) --
// without real VITE_FIREBASE_* values (e.g. a fresh clone using .env.example as-is),
// initializeApp/getAuth still succeed, but getAnalytics throws synchronously on an
// incomplete config. That exception used to happen at module-import time, before
// main.js ever reached app.mount(), so the whole SPA failed to boot with nothing but
// a blank page (the actual error only visible in the browser console). Guard each
// step so a missing Firebase config degrades to "Google sign-in unavailable" instead
// of taking down the entire app.
let app = null
let auth = null
let googleProvider = null
let analytics = null

try {
    app = initializeApp(firebaseConfig)
    auth = getAuth(app)
    googleProvider = new GoogleAuthProvider()
    googleProvider.setCustomParameters({
        prompt: 'select_account'
    })

    if (typeof window !== 'undefined' && firebaseConfig.measurementId) {
        isAnalyticsSupported()
            .then((supported) => {
                if (supported) {
                    analytics = getAnalytics(app)
                }
            })
            .catch(() => {
                // Analytics is non-essential -- ignore.
            })
    }
} catch (err) {
    console.warn(
        '[firebase] Initialization failed -- Google sign-in/analytics will be unavailable. ' +
        'Set real VITE_FIREBASE_* values in frontend/.env to enable them.',
        err
    )
}

export { auth, googleProvider, analytics }

export default app
