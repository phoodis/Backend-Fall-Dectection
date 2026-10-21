import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useBackendStore = defineStore('backend', () => {
    // รายการ backend ที่สามารถเลือกได้
    const backends = [
        { name: 'ตรวจจับคนล้ม', url: 'http://localhost:8932/api' },
        { name: 'ตรวจคนตกเตียง', url: 'http://localhost:8932/api' }
    ]

    // อ่าน index ที่บันทึกไว้ใน localStorage ถ้ามี
    let savedIndex = null
    try {
      savedIndex = localStorage.getItem('selectedBackendIndex')
    } catch (e) {
      savedIndex = null
    }
    const initialIndex = (savedIndex !== null && backends[savedIndex]) ? Number(savedIndex) : 0
    const selectedBackend = ref(backends[initialIndex])
    const isSwitching = ref(false) // สำหรับแสดง loading

    function setBackend(index, afterSwitchCallback) {
        if (index >= 0 && index < backends.length) {
            isSwitching.value = true
            selectedBackend.value = backends[index]
            try {
                localStorage.setItem('selectedBackendIndex', index)
            } catch (e) {}
            if (typeof afterSwitchCallback === 'function') {
                Promise.resolve(afterSwitchCallback()).finally(() => {
                    isSwitching.value = false
                })
            } else {
                isSwitching.value = false
            }
        }
    }

    // ฟังก์ชันสำหรับยืนยันก่อนเปลี่ยน backend
    function confirmBackendChange(index, onConfirm, onCancel) {
        const backendName = backends[index]?.name || ''
        if (!backendName) return
        // ใช้ window.confirm (หรือจะให้ UI เรียก dialog เองก็ได้)
        if (window.confirm(`คุณต้องการเปลี่ยนโหมดเป็น "${backendName}" หรือไม่?`)) {
            if (typeof onConfirm === 'function') onConfirm()
        } else {
            if (typeof onCancel === 'function') onCancel()
        }
    }

    return { backends, selectedBackend, setBackend, confirmBackendChange, isSwitching }
})
