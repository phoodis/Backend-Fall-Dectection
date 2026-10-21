<template>
  <div v-if="!isOnline" class="network-status-alert">
    <svg xmlns="http://www.w3.org/2000/svg" class="icon" viewBox="0 0 24 24">
      <path d="M3 6H21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      <path d="M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      <path d="M7 18H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
    </svg>
    <span>ไม่มีการเชื่อมต่ออินเทอร์เน็ต</span>
    <button @click="checkConnection" class="retry-btn">ลองใหม่</button>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const isOnline = ref(navigator.onLine)

function updateOnlineStatus() {
  isOnline.value = navigator.onLine
}

function checkConnection() {
  // ปรับปรุงการตรวจสอบการเชื่อมต่อให้ไม่ใช้ API ที่อาจไม่มี
  try {
    const testImage = new Image()
    testImage.src = 'https://www.google.com/favicon.ico?' + new Date().getTime()
    testImage.onload = function () {
      isOnline.value = true
    }
    testImage.onerror = function () {
      isOnline.value = false
    }
  } catch (e) {
    isOnline.value = navigator.onLine
  }
}

// ตรวจสอบการเชื่อมต่อเมื่อเริ่มต้น
onMounted(() => {
  window.addEventListener('online', updateOnlineStatus)
  window.addEventListener('offline', updateOnlineStatus)
  // ตรวจสอบสถานะการเชื่อมต่อเมื่อเริ่มต้น
  if (!navigator.onLine) {
    checkConnection()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('online', updateOnlineStatus)
  window.removeEventListener('offline', updateOnlineStatus)
})
</script>

<style scoped>
.network-status-alert {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  background-color: #fef2f2;
  color: #b91c1c;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  z-index: 2000;
  animation: slideDown 0.3s ease-out forwards;
}

.icon {
  width: 18px;
  height: 18px;
}

.retry-btn {
  background: none;
  border: 1px solid currentColor;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  border-radius: 4px;
  cursor: pointer;
  margin-left: 0.5rem;
}

@keyframes slideDown {
  from {
    transform: translateY(-100%);
  }
  to {
    transform: translateY(0);
  }
}
</style>
