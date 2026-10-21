<template>
  <div class="system-logs">
    <h1 class="page-title">บันทึกการทำงานของระบบ</h1>

    <div v-if="!isAdmin" class="access-denied">
      <div class="alert alert-warning">
        <h3>ไม่มีสิทธิ์เข้าถึง</h3>
        <p>หน้านี้สำหรับผู้ดูแลระบบเท่านั้น</p>
      </div>
    </div>

    <div v-else class="card">
      <div class="toolbar">
        <div class="filters">
          <label class="filter">
            <span>ระดับ</span>
            <select v-model="level" @change="reload" class="form-input">
              <option value="">ทั้งหมด</option>
              <option v-for="l in levels" :key="l" :value="l">{{ levelText(l) }}</option>
            </select>
          </label>

          <label class="filter">
            <span>ส่วนของระบบ</span>
            <select v-model="component" @change="reload" class="form-input">
              <option value="">ทั้งหมด</option>
              <option v-for="c in components" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
        </div>

        <div class="toolbar-right">
          <label class="auto-refresh">
            <input type="checkbox" v-model="autoRefresh" />
            <span>รีเฟรชอัตโนมัติ</span>
          </label>
          <button class="btn btn-secondary" @click="reload" :disabled="isLoading">
            {{ isLoading ? 'กำลังโหลด...' : 'รีเฟรช' }}
          </button>
        </div>
      </div>

      <div v-if="errorMessage" class="alert alert-error">{{ errorMessage }}</div>

      <div class="table-scroll">
        <table class="log-table">
          <thead>
            <tr>
              <th class="col-time">เวลา</th>
              <th class="col-level">ระดับ</th>
              <th class="col-component">ส่วนของระบบ</th>
              <th>รายละเอียด</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!logs.length && !isLoading">
              <td colspan="4" class="empty">ไม่มีบันทึกตามเงื่อนไขที่เลือก</td>
            </tr>
            <tr v-for="log in logs" :key="log.id">
              <td class="col-time">{{ formatTime(log.timestamp) }}</td>
              <td class="col-level">
                <span class="level-badge" :class="'level-' + (log.level || '').toLowerCase()">
                  {{ levelText(log.level) }}
                </span>
              </td>
              <td class="col-component">{{ log.component || '-' }}</td>
              <td class="message">{{ log.message }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="pager">
        <button class="btn btn-secondary" @click="go(page - 1)" :disabled="page <= 1 || isLoading">
          ก่อนหน้า
        </button>
        <span class="pager-info">
          หน้า {{ page }} จาก {{ pages || 1 }} · ทั้งหมด {{ total }} รายการ
        </span>
        <button class="btn btn-secondary" @click="go(page + 1)" :disabled="page >= pages || isLoading">
          ถัดไป
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import systemLogService from '@/services/systemLogService'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const logs = ref([])
const levels = ref([])
const components = ref([])
const level = ref('')
const component = ref('')
const page = ref(1)
const pages = ref(1)
const total = ref(0)
const isLoading = ref(false)
const errorMessage = ref('')
const autoRefresh = ref(false)
let timer = null

// Thai labels for the four levels the backend emits, so the page reads the same way as the
// rest of the UI. Unknown levels fall through unchanged rather than being hidden.
const LEVEL_TEXT = {
  INFO: 'ปกติ',
  WARNING: 'เตือน',
  ERROR: 'ผิดพลาด',
  CRITICAL: 'วิกฤต',
}

function levelText(l) {
  return LEVEL_TEXT[l] || l || '-'
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('th-TH', { dateStyle: 'short', timeStyle: 'medium' })
}

async function load() {
  if (!isAdmin.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await systemLogService.fetchSystemLogs({
      page: page.value, perPage: 50, level: level.value, component: component.value,
    })
    logs.value = res.logs || []
    pages.value = res.pages || 1
    total.value = res.total || 0
  } catch (e) {
    errorMessage.value = 'โหลดบันทึกไม่สำเร็จ: ' + e.message
  } finally {
    isLoading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function go(p) {
  if (p < 1 || (pages.value && p > pages.value)) return
  page.value = p
  load()
}

watch(autoRefresh, (on) => {
  clearInterval(timer)
  // 10s: system logs are written on camera start/stop and on errors, so anything faster is
  // just load for no new information.
  if (on) timer = setInterval(load, 10000)
})

onMounted(async () => {
  if (!isAdmin.value) return
  try {
    const [l, c] = await Promise.all([
      systemLogService.fetchLevels(),
      systemLogService.fetchComponents(),
    ])
    levels.value = l || []
    components.value = (c || []).filter(Boolean)
  } catch (e) {
    // Filters are a convenience; the log list itself still works without them.
    errorMessage.value = 'โหลดตัวกรองไม่สำเร็จ: ' + e.message
  }
  load()
})

onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.system-logs {
  padding: 1.5rem;
}

.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 1.25rem;
  color: #111827;
}

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  padding: 1.25rem;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.filters {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.filter {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.8rem;
  color: #374151;
}

.form-input {
  padding: 0.4rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 0.85rem;
  min-width: 11rem;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.auto-refresh {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: #374151;
}

.btn {
  padding: 0.4rem 0.9rem;
  border-radius: 0.375rem;
  border: 1px solid #d1d5db;
  background: #f9fafb;
  /* main.css's .btn-secondary sets color: white for its dark grey background. Overriding the
     background here without the colour left white text on a near-white button -- the pager
     read as two empty grey boxes. */
  color: #374151;
  font-size: 0.85rem;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.55;
  cursor: default;
}

/* The message column can be long; it scrolls inside the table rather than pushing the page
   sideways. */
.table-scroll {
  overflow-x: auto;
}

.log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.log-table th,
.log-table td {
  text-align: left;
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
}

.log-table th {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
}

.col-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  color: #6b7280;
}

.col-component {
  white-space: nowrap;
  color: #374151;
}

.message {
  color: #111827;
  word-break: break-word;
}

.empty {
  text-align: center;
  color: #6b7280;
  padding: 1.5rem;
}

.level-badge {
  display: inline-block;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  white-space: nowrap;
}

.level-info {
  background: #e0f2fe;
  color: #075985;
}

.level-warning {
  background: #fef3c7;
  color: #92400e;
}

.level-error {
  background: #fee2e2;
  color: #b91c1c;
}

.level-critical {
  background: #b91c1c;
  color: #fff;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1rem;
}

.pager-info {
  font-size: 0.8rem;
  color: #6b7280;
}

.alert {
  padding: 0.75rem 1rem;
  border-radius: 0.375rem;
  margin-bottom: 1rem;
}

.alert-error {
  background: #fee2e2;
  color: #b91c1c;
}

.alert-warning {
  background: #fef3c7;
  color: #92400e;
}
</style>
