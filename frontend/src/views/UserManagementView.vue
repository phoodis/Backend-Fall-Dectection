<template>
  <div class="user-management">
    <div class="page-header">
      <h1 class="page-title">จัดการผู้ใช้</h1>
      <div class="header-actions">
        <button @click="showCreateModal = true" class="btn btn-primary">
          + เพิ่มผู้ใช้ใหม่
        </button>
        <button @click="goToHome" class="btn btn-secondary">กลับหน้าหลัก</button>
      </div>
    </div>

    <div v-if="message" :class="`alert alert-${messageType} notification`">
      {{ message }}
    </div>

    <!-- แสดงสถิติ -->
    <div class="stats-container" v-if="dashboardData">
      <div class="stat-card">
        <h3>ผู้ใช้ทั้งหมด</h3>
        <p class="stat-number">{{ dashboardData.users?.total || 0 }}</p>
      </div>
      <div class="stat-card">
        <h3>ผู้ดูแลระบบ</h3>
        <p class="stat-number">{{ dashboardData.users?.admins || 0 }}</p>
      </div>
      <div class="stat-card">
        <h3>ผู้ใช้ทั่วไป</h3>
        <p class="stat-number">{{ dashboardData.users?.regular_users || 0 }}</p>
      </div>
      <div class="stat-card">
        <h3>กล้องทั้งหมด</h3>
        <p class="stat-number">{{ dashboardData.cameras?.total || 0 }}</p>
      </div>
    </div>

    <!-- รายการผู้ใช้ -->
    <div class="users-container">
      <div class="card">
        <h2 class="card-title">รายการผู้ใช้</h2>

        <!-- Search Filter -->
        <SearchFilter
          placeholder="ค้นหาผู้ใช้..."
          @search="handleSearch"
          @clear="clearSearch"
        />

        <div v-if="isLoading" class="loading-state">
          <p>กำลังโหลดข้อมูล...</p>
        </div>

        <div v-else-if="filteredUsers.length === 0" class="empty-state">
          <p>{{ searchQuery ? 'ไม่พบผู้ใช้ที่ค้นหา' : 'ยังไม่มีผู้ใช้ในระบบ' }}</p>
        </div>

        <div v-else class="users-list">
          <div v-for="user in filteredUsers" :key="user.id" class="user-item">
            <div class="user-info">
              <h3 class="user-name">{{ user.username }}</h3>
              <p class="user-role" :class="getRoleClass(user.role)">{{ getRoleText(user.role) }}</p>
              <div class="user-details">
                <div class="user-stats" v-if="user.stats">
                  <span>กล้อง: {{ user.stats.total_cameras || 0 }}</span>
                  <span>ใช้งาน: {{ user.stats.active_cameras || 0 }}</span>
                  <span>ประเมิน: {{ user.stats.total_assessments || 0 }}</span>
                </div>

                
              </div>
            </div>
            <div class="user-actions">
              <button
                @click="startEditUser(user)"
                class="btn btn-sm btn-secondary"
                :disabled="user.id === currentUser?.id"
              >
                แก้ไข
              </button>
              <button
                @click="deleteUser(user)"
                class="btn btn-sm btn-danger"
                :disabled="user.id === currentUser?.id"
              >
                ลบ
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal สร้างผู้ใช้ใหม่ -->
    <div v-if="showCreateModal" class="modal-overlay">
      <div class="modal-content">
        <div class="modal-header">
          <h3>เพิ่มผู้ใช้ใหม่</h3>
          <button @click="closeCreateModal" class="modal-close-btn">&times;</button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="createUser">
            <div class="form-group">
              <label for="new-username" class="form-label">
                ชื่อผู้ใช้ <span class="required">*</span>
              </label>
              <input
                type="text"
                id="new-username"
                v-model="newUser.username"
                class="form-input"
                placeholder="ชื่อผู้ใช้"
                required
                autofocus
              />
              <small
                  v-if="newUser.username && !/^[A-Za-z0-9]+$/.test(newUser.username)"
                  style="color:red"
                >
                  ชื่อผู้ใช้ต้องเป็นภาษาอังกฤษและตัวเลขเท่านั้น
                </small>
            </div>

            <div class="form-group">
              <label for="new-password" class="form-label">
                รหัสผ่าน <span class="required">*</span>
              </label>
              <input
                type="password"
                id="new-password"
                v-model="newUser.password"
                class="form-input"
                placeholder="รหัสผ่าน"
                required
                minlength="6"
              />
            </div>

            <div class="form-group">
              <label for="new-role" class="form-label">
                บทบาท <span class="required">*</span>
              </label>
              <select
                id="new-role"
                v-model="newUser.role"
                class="form-input"
                required
              >
                <option value="user">ผู้ใช้ทั่วไป</option>
                <option value="admin">ผู้ดูแลระบบ</option>
              </select>
            </div>

            

            <div class="form-actions">
              <button type="button" @click="closeCreateModal" class="btn btn-secondary">
                ยกเลิก
              </button>
              <button type="submit" class="btn btn-primary" :disabled="isSubmitting">
                {{ isSubmitting ? 'กำลังสร้าง...' : 'สร้างผู้ใช้' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Modal แก้ไขผู้ใช้ -->
    <div v-if="showEditModal" class="modal-overlay">
      <div class="modal-content">
        <div class="modal-header">
          <h3>แก้ไขผู้ใช้</h3>
          <button @click="closeEditModal" class="modal-close-btn">&times;</button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="updateUser">
            <div class="form-group">
              <label for="edit-username" class="form-label">
                ชื่อผู้ใช้ <span class="required">*</span>
              </label>
              <input
                type="text"
                id="edit-username"
                v-model="editingUser.username"
                class="form-input"
                placeholder="ชื่อผู้ใช้"
                required
              />
            </div>

            <div class="form-group">
              <label for="edit-password" class="form-label">
                รหัสผ่านใหม่ (เว้นว่างหากไม่ต้องการเปลี่ยน)
              </label>
              <input
                type="password"
                id="edit-password"
                v-model="editingUser.password"
                class="form-input"
                placeholder="รหัสผ่านใหม่"
                minlength="6"
              />
            </div>

            <div class="form-group">
              <label for="edit-role" class="form-label">
                บทบาท <span class="required">*</span>
              </label>
              <select
                id="edit-role"
                v-model="editingUser.role"
                class="form-input"
                required
                :disabled="editingUser.id === currentUser?.id"
              >
                <option value="user">ผู้ใช้ทั่วไป</option>
                <option value="admin">ผู้ดูแลระบบ</option>
              </select>
              <small class="form-help" v-if="editingUser.id === currentUser?.id">
                ไม่สามารถเปลี่ยนบทบาทของตนเองได้
              </small>
            </div>

            

            <div class="form-actions">
              <button type="button" @click="closeEditModal" class="btn btn-secondary">
                ยกเลิก
              </button>
              <button type="submit" class="btn btn-primary" :disabled="isSubmitting">
                {{ isSubmitting ? 'กำลังอัพเดท...' : 'อัพเดทผู้ใช้' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import adminService from '@/services/adminService'
import SearchFilter from '@/components/common/SearchFilter.vue'

const authStore = useAuthStore()
const router = useRouter()

// ตรวจสอบสิทธิ์
const isAdmin = computed(() => authStore.isAdmin)
const currentUser = computed(() => authStore.user)

// ถ้าไม่ใช่ admin ให้ redirect
if (!isAdmin.value) {
  router.push('/dashboard')
}

// State
const users = ref([])
const dashboardData = ref(null)
const message = ref('')
const messageType = ref('')
const isLoading = ref(false)
const isSubmitting = ref(false)
const searchQuery = ref('')

// Modal states
const showCreateModal = ref(false)
const showEditModal = ref(false)

// Form data
const newUser = ref({
  username: '',
  password: '',
  role: 'user',
})

const editingUser = ref({
  id: null,
  username: '',
  password: '',
  role: 'user',
})

// Computed
const filteredUsers = computed(() => {
  if (!searchQuery.value) return users.value

  return users.value.filter(user =>
    user.username.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

// Methods
async function loadData() {
  isLoading.value = true
  try {
    // โหลดข้อมูลผู้ใช้และ dashboard
    const [usersResponse, dashboardResponse] = await Promise.all([
      adminService.getUsers(),
      adminService.getDashboard()
    ])

    users.value = usersResponse.users || []
    dashboardData.value = dashboardResponse
  } catch (error) {
    message.value = 'เกิดข้อผิดพลาดในการโหลดข้อมูล'
    messageType.value = 'danger'
    console.error('Failed to load data:', error)
  } finally {
    isLoading.value = false
  }
}

async function createUser() {
  if (!newUser.value.username || !newUser.value.password) {
    message.value = 'กรุณากรอกข้อมูลให้ครบถ้วน'
    messageType.value = 'danger'
    return
  }

  isSubmitting.value = true
  try {
    await adminService.createUser(newUser.value)
    message.value = `สร้างผู้ใช้ ${newUser.value.username} เรียบร้อยแล้ว`
    messageType.value = 'success'
    closeCreateModal()
    await loadData() // โหลดข้อมูลใหม่
  } catch (error) {
    message.value = error.message || 'เกิดข้อผิดพลาดในการสร้างผู้ใช้'
    messageType.value = 'danger'
  } finally {
    isSubmitting.value = false
  }
}

async function updateUser() {
  if (!editingUser.value.username) {
    message.value = 'กรุณากรอกชื่อผู้ใช้'
    messageType.value = 'danger'
    return
  }

  isSubmitting.value = true
  try {
    const updateData = {
      username: editingUser.value.username,
      role: editingUser.value.role,
    }

    // เพิ่มรหัสผ่านถ้ามีการกรอก
    if (editingUser.value.password) {
      updateData.password = editingUser.value.password
    }

    await adminService.updateUser(editingUser.value.id, updateData)
    message.value = `อัพเดทผู้ใช้ ${editingUser.value.username} เรียบร้อยแล้ว`
    messageType.value = 'success'
    closeEditModal()
    await loadData() // โหลดข้อมูลใหม่
  } catch (error) {
    message.value = error.message || 'เกิดข้อผิดพลาดในการอัพเดทผู้ใช้'
    messageType.value = 'danger'
  } finally {
    isSubmitting.value = false
  }
}

async function deleteUser(user) {
  if (user.id === currentUser.value?.id) {
    message.value = 'ไม่สามารถลบบัญชีของตนเองได้'
    messageType.value = 'danger'
    return
  }

  if (!confirm(`ต้องการลบผู้ใช้ ${user.username} ใช่หรือไม่?`)) {
    return
  }

  try {
    await adminService.deleteUser(user.id)
    message.value = `ลบผู้ใช้ ${user.username} เรียบร้อยแล้ว`
    messageType.value = 'info'
    await loadData() // โหลดข้อมูลใหม่
  } catch (error) {
    message.value = error.message || 'เกิดข้อผิดพลาดในการลบผู้ใช้'
    messageType.value = 'danger'
  }
}


function startEditUser(user) {
  editingUser.value = {
    id: user.id,
    username: user.username,
    password: '',
    role: user.role,
  }
  showEditModal.value = true
}

function closeCreateModal() {
  showCreateModal.value = false
  newUser.value = {
    username: '',
    password: '',
    role: 'user',
  }
}

function closeEditModal() {
  showEditModal.value = false
  editingUser.value = {
    id: null,
    username: '',
    password: '',
    role: 'user',
  }
}

function getRoleText(role) {
  return role === 'admin' ? 'ผู้ดูแลระบบ' : 'ผู้ใช้ทั่วไป'
}

function getRoleClass(role) {
  return role === 'admin' ? 'role-admin' : 'role-user'
}

function handleSearch(query) {
  searchQuery.value = query
}

function clearSearch() {
  searchQuery.value = ''
}

function goToHome() {
  router.push('/dashboard')
}

// Helper functions for state management
function saveUserManagementState() {
  const state = {
    searchQuery: searchQuery.value
  }
  localStorage.setItem('userManagementState', JSON.stringify(state))
}

function loadUserManagementState() {
  const savedState = localStorage.getItem('userManagementState')
  if (savedState) {
    try {
      const state = JSON.parse(savedState)
      searchQuery.value = state.searchQuery || ''
    } catch (e) {
      console.error('Error loading user management state:', e)
    }
  }
}

// Watch for search query changes
watch(searchQuery, () => {
  saveUserManagementState()
})

// Lifecycle
onMounted(() => {
  loadUserManagementState()
  loadData()
})
</script>

<style scoped>
.user-management {
  padding-bottom: 2rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.header-actions {
  display: flex;
  gap: 1rem;
}

.stats-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: white;
  padding: 1.5rem;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  text-align: center;
}

.stat-card h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
  color: #6b7280;
}

.stat-number {
  margin: 0;
  font-size: 2rem;
  font-weight: bold;
  color: #1f2937;
}

.users-container {
  max-width: 800px;
  margin: 0 auto;
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.user-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
  transition: all 0.2s ease;
}

.user-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.user-info {
  flex: 1;
}

.user-name {
  margin: 0 0 0.25rem 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
}

.user-role {
  margin: 0 0 0.5rem 0;
  font-size: 0.875rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  display: inline-block;
}

.role-admin {
  background: #fef3c7;
  color: #92400e;
}

.role-user {
  background: #dbeafe;
  color: #1e40af;
}

.user-stats {
  font-size: 0.875rem;
  color: #6b7280;
  margin-bottom: 0.5rem;
}

.user-stats span {
  margin-right: 1rem;
}





.user-details {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.user-actions {
  display: flex;
  gap: 0.5rem;
}

.loading-state, .empty-state {
  text-align: center;
  padding: 2rem;
  color: #6b7280;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background-color: white;
  border-radius: 8px;
  max-width: 500px;
  width: 100%;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  animation: modal-appear 0.3s ease-out;
}

@keyframes modal-appear {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-header {
  padding: 1rem;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.modal-close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #6b7280;
}

.modal-body {
  padding: 1.5rem;
}

.form-group {
  margin-bottom: 1rem;
}

.form-label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
  color: #374151;
}

.required {
  color: #ef4444;
}

.form-input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 1rem;
}

.form-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.form-input:disabled {
  background-color: #f3f4f6;
  color: #6b7280;
}

.form-help {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.875rem;
  color: #6b7280;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  margin-top: 1.5rem;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .user-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .user-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .stats-container {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
