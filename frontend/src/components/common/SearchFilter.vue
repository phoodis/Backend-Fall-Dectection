<template>
  <div class="search-filter">
    <div class="search-input-wrapper">
      <input
        type="text"
        :placeholder="placeholder"
        v-model="searchQuery"
        class="search-input"
        @input="handleSearch"
      />
      <button v-if="searchQuery" @click="clearSearch" class="clear-button">&times;</button>
      <svg
        class="search-icon"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    </div>
    <div v-if="showFilters" class="filters">
      <slot name="filters"></slot>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  placeholder: {
    type: String,
    default: 'ค้นหา...',
  },
  showFilters: {
    type: Boolean,
    default: false,
  },
  delay: {
    type: Number,
    default: 300,
  },
})

const emit = defineEmits(['search', 'clear'])

const searchQuery = ref('')
let searchTimer = null

function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    emit('search', searchQuery.value)
  }, props.delay)
}

function clearSearch() {
  searchQuery.value = ''
  emit('clear')
}

watch(searchQuery, (newValue) => {
  if (!newValue) {
    emit('clear')
  }
})
</script>

<style scoped>
.search-filter {
  margin-bottom: 1rem;
}

.search-input-wrapper {
  position: relative;
  width: 100%;
}

.search-input {
  width: 100%;
  padding: 0.75rem 2.5rem 0.75rem 2.5rem;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  font-size: 0.95rem;
  transition: all 0.2s ease;
}

.search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  outline: none;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 18px;
  height: 18px;
  color: #6b7280;
}

.clear-button {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #6b7280;
  font-size: 1.2rem;
  cursor: pointer;
  height: 22px;
  width: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.clear-button:hover {
  background-color: #f3f4f6;
}

.filters {
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
