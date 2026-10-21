<template>
  <transition name="notification-fade">
    <div v-if="show" class="notification" :class="typeClass">
      <div class="notification-icon">
        <!-- Success Icon -->
        <svg
          v-if="type === 'success'"
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M8 12l2 2 4-4"></path>
        </svg>

        <!-- Error Icon -->
        <svg
          v-else-if="type === 'error'"
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="15" y1="9" x2="9" y2="15"></line>
          <line x1="9" y1="9" x2="15" y2="15"></line>
        </svg>

        <!-- Warning Icon -->
        <svg
          v-else-if="type === 'warning'"
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
          ></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>

        <!-- Info Icon -->
        <svg
          v-else
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="16"></line>
          <line x1="12" y1="16" x2="12" y2="16"></line>
        </svg>
      </div>

      <div class="notification-content">
        <h3 v-if="title" class="notification-title">{{ title }}</h3>
        <p class="notification-message">{{ message }}</p>
        <small v-if="showTime" class="notification-time">{{ formattedTime }}</small>

        <!-- เพิ่มปุ่มยืนยันการแจ้งเตือน -->
        <div v-if="requiresAcknowledgment" class="notification-actions">
          <button @click="acknowledgeNotification" class="notification-acknowledge">รับทราบ</button>
        </div>
      </div>

      <button v-if="closable" @click="closeNotification" class="notification-close">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>
  </transition>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  title: {
    type: String,
    default: '',
  },
  message: {
    type: String,
    required: true,
  },
  type: {
    type: String,
    default: 'info',
    validator: (value) => ['success', 'error', 'warning', 'info'].includes(value),
  },
  duration: {
    type: Number,
    default: 5000, // 5 วินาที
  },
  closable: {
    type: Boolean,
    default: true,
  },
  showTime: {
    type: Boolean,
    default: true,
  },
  autoClose: {
    type: Boolean,
    default: true,
  },
  requiresAcknowledgment: {
    type: Boolean,
    default: false, // เพิ่ม prop ใหม่สำหรับกำหนดว่าต้องยืนยันหรือไม่
  },
  notificationId: {
    type: [String, Number],
    default: null,
  },
})

const emit = defineEmits(['close', 'acknowledge'])
const show = ref(true)
const timer = ref(null)

const typeClass = computed(() => `notification-${props.type}`)

const formattedTime = computed(() => {
  return new Date().toLocaleTimeString()
})

function closeNotification() {
  show.value = false
  if (timer.value) {
    clearTimeout(timer.value)
  }
  emit('close')
}

// เพิ่มฟังก์ชันสำหรับยืนยันการแจ้งเตือน
function acknowledgeNotification() {
  show.value = false
  if (timer.value) {
    clearTimeout(timer.value)
  }
  emit('acknowledge', props.notificationId)
}

onMounted(() => {
  if (props.autoClose && props.duration > 0 && !props.requiresAcknowledgment) {
    timer.value = setTimeout(() => {
      closeNotification()
    }, props.duration)
  }
})

onBeforeUnmount(() => {
  if (timer.value) {
    clearTimeout(timer.value)
  }
})
</script>

<style scoped>
.notification {
  display: flex;
  align-items: flex-start;
  padding: 16px;
  background-color: white;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
}

.notification::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
}

.notification-success {
  border-left: 4px solid #10b981;
}

.notification-success .notification-icon {
  color: #10b981;
}

.notification-error {
  border-left: 4px solid #ef4444;
}

.notification-error .notification-icon {
  color: #ef4444;
}

.notification-warning {
  border-left: 4px solid #f59e0b;
}

.notification-warning .notification-icon {
  color: #f59e0b;
}

.notification-info {
  border-left: 4px solid #3b82f6;
}

.notification-info .notification-icon {
  color: #3b82f6;
}

.notification-icon {
  flex-shrink: 0;
  margin-right: 16px;
}

.notification-content {
  flex: 1;
}

.notification-title {
  margin: 0 0 4px 0;
  font-weight: 600;
  font-size: 16px;
  color: #1e293b;
}

.notification-message {
  margin: 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.5;
}

.notification-time {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.notification-close {
  background: none;
  border: none;
  color: #94a3b8;
  padding: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s ease;
}

.notification-close:hover {
  color: #64748b;
}

.notification-close svg {
  width: 18px;
  height: 18px;
}

.notification-fade-enter-active,
.notification-fade-leave-active {
  transition: all 0.3s ease;
}

.notification-fade-enter-from {
  transform: translateX(30px);
  opacity: 0;
}

.notification-fade-leave-to {
  transform: translateX(30px);
  opacity: 0;
}

.notification-actions {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.notification-acknowledge {
  background-color: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.notification-acknowledge:hover {
  background-color: #2563eb;
}
</style>
