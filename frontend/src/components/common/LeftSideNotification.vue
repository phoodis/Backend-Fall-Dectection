<template>
  <div class="left-notifications-container">
    <transition-group name="notification-slide">
      <div
        v-for="notification in notifications"
        :key="notification.id"
        class="left-notification"
        :class="getNotificationClass(notification.type)"
      >
        <div class="notification-icon">
          <!-- Success Icon -->
          <svg
            v-if="notification.type === 'success'"
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
            v-else-if="notification.type === 'error'"
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
            v-else-if="notification.type === 'warning'"
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
          <h3 v-if="notification.title" class="notification-title">{{ notification.title }}</h3>
          <p class="notification-message">{{ notification.message }}</p>
          <small v-if="showTimestamp" class="notification-time">
            {{ formatTime(notification.timestamp) }}
          </small>
        </div>

        <button class="notification-close" @click="dismissNotification(notification.id)">
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
    </transition-group>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLeftNotificationStore } from '@/stores/leftNotification'

const props = defineProps({
  showTimestamp: {
    type: Boolean,
    default: true,
  },
})

const leftNotificationStore = useLeftNotificationStore()
const notifications = computed(() => leftNotificationStore.notifications)

function dismissNotification(id) {
  leftNotificationStore.removeNotification(id)
}

function getNotificationClass(type) {
  return {
    'notification-success': type === 'success',
    'notification-warning': type === 'warning',
    'notification-error': type === 'error',
    'notification-info': type === 'info' || !type,
  }
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleTimeString()
}
</script>

<style scoped>
.left-notifications-container {
  position: fixed;
  left: 0;
  top: 80px;
  width: 300px;
  max-height: 80vh;
  overflow-y: auto;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
}

.left-notification {
  display: flex;
  align-items: flex-start;
  background-color: white;
  border-radius: 0 8px 8px 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  padding: 12px;
  border-left-width: 4px;
  border-left-style: solid;
  transform-origin: left center;
  max-width: 300px;
}

.notification-success {
  border-left-color: #10b981;
}

.notification-success .notification-icon {
  color: #10b981;
}

.notification-error {
  border-left-color: #ef4444;
}

.notification-error .notification-icon {
  color: #ef4444;
}

.notification-warning {
  border-left-color: #f59e0b;
}

.notification-warning .notification-icon {
  color: #f59e0b;
}

.notification-info {
  border-left-color: #3b82f6;
}

.notification-info .notification-icon {
  color: #3b82f6;
}

.notification-icon {
  flex-shrink: 0;
  margin-right: 12px;
  width: 24px;
  height: 24px;
}

.notification-content {
  flex: 1;
  margin-right: 8px;
  overflow: hidden;
}

.notification-title {
  margin: 0 0 4px 0;
  font-weight: 600;
  font-size: 14px;
  color: #1e293b;
}

.notification-message {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.4;
}

.notification-time {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  color: #94a3b8;
}

.notification-close {
  background: none;
  border: none;
  color: #94a3b8;
  padding: 2px;
  height: 24px;
  width: 24px;
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
  width: 16px;
  height: 16px;
}

.notification-slide-enter-active,
.notification-slide-leave-active {
  transition: all 0.3s ease;
}

.notification-slide-enter-from {
  transform: translateX(-100%);
  opacity: 0;
}

.notification-slide-leave-to {
  transform: translateX(-100%);
  opacity: 0;
}

@media screen and (max-width: 768px) {
  .left-notifications-container {
    width: 260px;
    top: 60px;
  }
}
</style>
