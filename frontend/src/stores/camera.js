import { ref } from 'vue'
import { defineStore } from 'pinia'
import cameraService from '@/services/cameraService'

export const useCameraStore = defineStore('camera', () => {
  const cameras = ref([])
  const selectedCamera = ref(null)
  const isLoading = ref(false)
  const error = ref(null)

  // เพิ่มกล้องใหม่ (Admin only)
  async function addCamera(camera) {
    isLoading.value = true
    error.value = null

    try {
      // เรียกใช้ API
      const result = await cameraService.addCamera(camera)

      // เพิ่มกล้องลงใน state
      if (result.camera) {
        cameras.value.push(result.camera)
      }

      // เก็บข้อมูลใน localStorage เป็น fallback
      localStorage.setItem('cameras', JSON.stringify(cameras.value))

      return result.camera || result
    } catch (err) {
      error.value = err.message || 'เกิดข้อผิดพลาดในการเพิ่มกล้อง'
      throw error.value
    } finally {
      isLoading.value = false
    }
  }

  // เลือกกล้อง
  function selectCamera(camera) {
    selectedCamera.value = camera
  }

  // // ตั้งค่าสถานะกล้องที่เลือก
  // async function setSelectedCameraStatus(status) {
  //   if (!selectedCamera.value) return

  //   try {
  //     // เรียกใช้ API
  //     await cameraService.updateCameraStatus(selectedCamera.value.id, status)

  //     // อัพเดท state
  //     selectedCamera.value.status = status

  //     // อัพเดทกล้องในรายการด้วย
  //     const index = cameras.value.findIndex((cam) => cam.id === selectedCamera.value.id)
  //     if (index !== -1) {
  //       cameras.value[index].status = status
  //     }

  //     // อัพเดท localStorage
  //     localStorage.setItem('cameras', JSON.stringify(cameras.value))
  //   } catch (err) {
  //     console.error('Error updating camera status:', err)
  //   }
  // }

  // ลบกล้อง รับเป็น id หรือ object
  async function removeCamera(camera) {
    isLoading.value = true
    error.value = null

    try {
      const cameraId = typeof camera === 'object' ? camera.id : camera

      // เรียกใช้ API
      await cameraService.deleteCamera(cameraId)

      // ลบกล้องออกจาก state
      const index = cameras.value.findIndex((cam) => cam.id === cameraId)
      if (index !== -1) {
        cameras.value.splice(index, 1)
      }

      // ล้างค่ากล้องที่เลือกถ้ามันถูกลบ
      if (selectedCamera.value && selectedCamera.value.id === cameraId) {
        selectedCamera.value = null
      }

      // อัปเดต localStorage
      localStorage.setItem('cameras', JSON.stringify(cameras.value))
    } catch (err) {
      error.value = err.message || 'เกิดข้อผิดพลาดในการลบกล้อง'
      throw error.value
    } finally {
      isLoading.value = false
    }
  }

  // // อัพเดทสถานะของกล้อง
  // async function updateCameraStatus(cameraId, status) {
  //   isLoading.value = true
  //   error.value = null

  //   try {
  //     // เรียกใช้ API
  //     await cameraService.updateCameraStatus(cameraId, status)

  //     // อัพเดท state
  //     const camera = cameras.value.find((cam) => cam.id === cameraId)
  //     if (camera) {
  //       camera.status = status

  //       // อัพเดตกล้องที่เลือกถ้าเป็นกล้องเดียวกัน
  //       if (selectedCamera.value && selectedCamera.value.id === cameraId) {
  //         selectedCamera.value.status = status
  //       }

  //       // อัปเดต localStorage
  //       localStorage.setItem('cameras', JSON.stringify(cameras.value))
  //     }
  //   } catch (err) {
  //     error.value = err.message || 'เกิดข้อผิดพลาดในการอัพเดตสถานะกล้อง'
  //   } finally {
  //     isLoading.value = false
  //   }
  // }

  // อัพเดทกล้อง (Admin only)
  async function updateCamera(cameraId, updatedData) {
    isLoading.value = true
    error.value = null

    try {
      // เรียกใช้ API
      const result = await cameraService.updateCamera(cameraId, updatedData)

      // อัพเดทใน state
      const index = cameras.value.findIndex((cam) => cam.id === cameraId)
      if (index !== -1) {
        // ใช้ข้อมูลที่อัพเดทจาก API response หรือ merge กับข้อมูลเดิม
        const updatedCamera = result.camera || { ...cameras.value[index], ...updatedData }
        cameras.value[index] = updatedCamera

        // อัพเดตกล้องที่เลือกด้วยถ้าตรงกัน
        if (selectedCamera.value && selectedCamera.value.id === cameraId) {
          selectedCamera.value = updatedCamera
        }
      }

      // อัปเดต localStorage
      localStorage.setItem('cameras', JSON.stringify(cameras.value))

      return result
    } catch (err) {
      error.value = err.message || 'เกิดข้อผิดพลาดในการอัพเดทกล้อง'
      throw error.value
    } finally {
      isLoading.value = false
    }
  }

  // ตรวจสอบว่ากล้องมีอยู่หรือไม่
  function cameraExists(cameraId) {
    return cameras.value.some((cam) => cam.id === cameraId)
  }

  // โหลดกล้องจาก API
  async function loadCameras() {
    isLoading.value = true
    error.value = null

    try {
      // เรียกใช้ API
      const result = await cameraService.getAllCameras()
      // Ensure result is always an array
      cameras.value = Array.isArray(result) ? result : []

      // บันทึก fallback ใน localStorage
      localStorage.setItem('cameras', JSON.stringify(cameras.value))

      return cameras.value
    } catch (err) {
      // ถ้า API ไม่สำเร็จ ให้ลองโหลดจาก localStorage
      const storedCameras = localStorage.getItem('cameras')
      if (storedCameras) {
        try {
          const parsed = JSON.parse(storedCameras)
          cameras.value = Array.isArray(parsed) ? parsed : []
        } catch (parseError) {
          cameras.value = []
        }
      } else {
        cameras.value = []
      }

      error.value = err.message || 'เกิดข้อผิดพลาดในการโหลดรายการกล้อง'
      console.error('Error loading cameras:', err)
    } finally {
      isLoading.value = false
    }
  }

  // เรียกโหลดกล้องเมื่อสร้าง store
  function initStore() {
    // ลองโหลดจาก localStorage ก่อน (โดยไม่เรียก API)
    const storedCameras = localStorage.getItem('cameras')
    if (storedCameras) {
      try {
        const parsed = JSON.parse(storedCameras)
        cameras.value = Array.isArray(parsed) ? parsed : []
      } catch (error) {
        console.error('Error parsing stored cameras:', error)
        cameras.value = []
        localStorage.removeItem('cameras')
      }
    } else {
      cameras.value = []
    }
  }

  // เรียกฟังก์ชันเริ่มต้นทันทีที่สร้าง store (เฉพาะโหลด localStorage)
  initStore()

  return {
    cameras,
    selectedCamera,
    isLoading,
    error,
    addCamera,
    selectCamera,
    removeCamera,
    updateCamera,
    cameraExists,
    loadCameras,
  }
})
