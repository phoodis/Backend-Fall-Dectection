<template>
  <div class="error-container" :class="type">
    <div class="error-icon">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
        <path
          fill-rule="evenodd"
          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z"
          clip-rule="evenodd"
        />
      </svg>
    </div>
    <div class="error-content">
      <h3 v-if="title" class="error-title">{{ title }}</h3>
      <p class="error-message">{{ message }}</p>
      <button v-if="retryEnabled" @click="$emit('retry')" class="error-retry">ลองอีกครั้ง</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
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
    default: 'error',
    validator: (value) => ['error', 'warning', 'info'].includes(value),
  },
  retryEnabled: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['retry'])
</script>

<style scoped>
.error-container {
  display: flex;
  align-items: flex-start;
  padding: 1rem;
  border-radius: 0.375rem;
  margin-bottom: 1rem;
  gap: 0.75rem;
}

.error-container.error {
  background-color: #fee2e2;
  border-left: 4px solid #b91c1c;
  color: #991b1b;
}

.error-container.warning {
  background-color: #fff7ed;
  border-left: 4px solid #c2410c;
  color: #9a3412;
}

.error-container.info {
  background-color: #dbeafe;
  border-left: 4px solid #1e40af;
  color: #1e3a8a;
}

.error-icon {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
}

.error-content {
  flex: 1;
}

.error-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.error-message {
  margin: 0;
  font-size: 0.875rem;
}

.error-retry {
  background: none;
  border: none;
  color: currentColor;
  text-decoration: underline;
  font-size: 0.875rem;
  cursor: pointer;
  margin-top: 0.5rem;
  padding: 0.25rem 0;
}

.error-retry:hover {
  text-decoration: none;
}
</style>
