<template>
  <div class="thai-frat-detail card">
    <h1 class="page-title">แฟ้มข้อมูล Thai-FRAT</h1>

    <div v-if="loading" class="loading-message">
      <div class="spinner"></div>
      <p>กำลังโหลดข้อมูล...</p>
    </div>

    <div v-else-if="form">
      <div class="detail-row"><strong>ชื่อ-นามสกุล:</strong> {{ form.name }}</div>
      <div class="detail-row"><strong>เบอร์โทร:</strong> {{ form.tel || 'ไม่ระบุ' }}</div>
      <div class="detail-row"><strong>จังหวัด:</strong> {{ form.province || 'ไม่ระบุ' }}</div>
      <div class="detail-row"><strong>PDPA:</strong> <span :class="form.pdpa ? 'text-success' : 'text-danger'">{{ form.pdpa ? 'ยินยอม' : 'ไม่ยินยอม' }}</span></div>
      <div class="detail-row"><strong>คะแนนรวม:</strong> {{ form.score }} คะแนน</div>
      <div class="detail-row"><strong>ระดับความเสี่ยง:</strong> <span :class="getRiskClass(form.risk_level)">{{ form.risk_description || 'ไม่ระบุ' }}</span></div>
      <div class="detail-row"><strong>ข้อมูลแบบประเมิน:</strong></div>
      <div class="assessment-details">
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 1: ประวัติการพลัดตกหกล้ม</strong>
            <span class="score-badge">{{ form.q1_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q1_value || 'ไม่ระบุ' }}</div>
        </div>
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 2: มีการวินิจฉัยโรคมากกว่า 1 รายการ</strong>
            <span class="score-badge">{{ form.q2_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q2_value || 'ไม่ระบุ' }}</div>
        </div>
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 3: การช่วยในการเคลื่อนย้าย</strong>
            <span class="score-badge">{{ form.q3_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q3_value || 'ไม่ระบุ' }}</div>
        </div>
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 4: ให้สารละลายทางหลอดเลือดดำ (IV) / ใช้ Heparin lock</strong>
            <span class="score-badge">{{ form.q4_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q4_value || 'ไม่ระบุ' }}</div>
        </div>
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 5: การเดิน / การเคลื่อนย้าย</strong>
            <span class="score-badge">{{ form.q5_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q5_value || 'ไม่ระบุ' }}</div>
        </div>
        <div class="question-item">
          <div class="question-header">
            <strong>คำถามที่ 6: สภาพจิตใจ</strong>
            <span class="score-badge">{{ form.q6_score || 0 }} คะแนน</span>
          </div>
          <div class="question-answer">{{ form.q6_value || 'ไม่ระบุ' }}</div>
        </div>
      </div>
      <div v-if="form.created_at" class="detail-row"><strong>สร้างเมื่อ:</strong> {{ formatDate(form.created_at) }}</div>
      <div v-if="form.updated_at" class="detail-row"><strong>แก้ไขล่าสุด:</strong> {{ formatDate(form.updated_at) }}</div>
      <div v-if="form.creator_username" class="detail-row"><strong>ผู้สร้าง:</strong> {{ form.creator_username }}</div>
      <div v-if="!form.is_own && form.shared_by" class="detail-row"><strong>แชร์โดย:</strong> {{ form.shared_by }}</div>
      <div class="actions">
        <button v-if="form.is_own" class="btn btn-primary" @click="editForm">แก้ไข</button>
        <button v-if="form.is_own" class="btn btn-danger" @click="deleteForm">ลบ</button>
        <button v-if="form.is_own" class="btn btn-secondary" @click="showShareModal">แชร์</button>
        <button class="btn btn-secondary" @click="goBack">กลับ</button>
      </div>
      <div v-if="shareMessage" class="alert" :class="shareMessage.type">{{ shareMessage.text }}</div>
    </div>
    <div v-else class="empty-message">ไม่พบข้อมูลฟอร์ม</div>

    <!-- Share Modal -->
    <div v-if="showShareDialog" class="modal-overlay" @click="closeShareModal">
      <div class="modal-content" @click.stop>
        <button class="modal-close" @click="closeShareModal">&times;</button>
        <h3 class="modal-title">แชร์ข้อมูล Thai-FRAT</h3>
        <div class="form-group">
          <label class="form-label">อีเมลที่ต้องการแชร์</label>
          <input
            v-model="shareEmail"
            class="form-input"
            type="email"
            placeholder="กรอกอีเมล"
            @keyup.enter="shareFormWithUser"
          />
        </div>
        <div class="form-group">
          <label class="checkbox-label">
            <input v-model="includePersonalInfo" type="checkbox" />
            รวมข้อมูลส่วนบุคคล (ชื่อ, เบอร์โทร)
          </label>
        </div>
        <div class="modal-actions">
          <button
            class="btn btn-primary"
            @click="shareFormWithUser"
            :disabled="!shareEmail.trim() || sharingInProgress"
          >
            <span v-if="sharingInProgress">กำลังแชร์...</span>
            <span v-else>แชร์</span>
          </button>
          <button class="btn btn-secondary" @click="closeShareModal" :disabled="sharingInProgress">ยกเลิก</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useThaiFratStore } from '@/stores/thaiFrat'
import { getApiBaseUrl } from '@/config/api'

const route = useRoute()
const router = useRouter()
const thaiFratStore = useThaiFratStore()
const shareMessage = ref({ text: '', type: '' })
const loading = ref(true)

// Share modal variables
const showShareDialog = ref(false)
const shareEmail = ref('')
const includePersonalInfo = ref(true)
const sharingInProgress = ref(false)

const formId = route.params.id


// Load forms when component mounts
onMounted(async () => {
  loading.value = true
  try {
    await thaiFratStore.loadForms()
    // If form is not found in store, try to load it directly from API
    if (!form.value) {
      await loadSpecificAssessment()
    }
  } catch (error) {
    console.error('Error loading forms:', error)
    shareMessage.value = {
      text: 'ไม่สามารถโหลดข้อมูลได้',
      type: 'alert-error'
    }
  } finally {
    loading.value = false
  }
})

// Load specific assessment from backend
async function loadSpecificAssessment() {
  try {
    const baseUrl = getApiBaseUrl()
    const response = await fetch(`${baseUrl}/thai-frat/assessments/${formId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
      }
    })

    if (response.ok) {
      const data = await response.json()
      const assessment = data.assessment

      // Transform and add to store
      const assessmentForStore = {
        id: assessment.id,
        name: assessment.name,
        tel: assessment.tel,
        province: assessment.province || '', // Now included from API
        pdpa: assessment.pdpa_consent,
        score: assessment.total_score,
        risk_level: assessment.risk_level,
        risk_description: assessment.risk_description,
        q1_score: assessment.q1_score,
        q1_value: assessment.q1_value,
        q2_score: assessment.q2_score,
        q2_value: assessment.q2_value,
        q3_score: assessment.q3_score,
        q3_value: assessment.q3_value,
        q4_score: assessment.q4_score,
        q4_value: assessment.q4_value,
        q5_score: assessment.q5_score,
        q5_value: assessment.q5_value,
        q6_score: assessment.q6_score,
        q6_value: assessment.q6_value,
        created_at: assessment.created_at,
        updated_at: assessment.updated_at,
        creator_username: assessment.creator_username,
        is_own: true // Assume it's own if we can access it directly
      }

      thaiFratStore.addForm(assessmentForStore)
    } else {
      const error = await response.json()
      shareMessage.value = {
        text: `ไม่พบข้อมูล: ${error.error || 'Assessment not found'}`,
        type: 'alert-error'
      }
    }
  } catch (error) {
    console.error('Error loading specific assessment:', error)
    shareMessage.value = {
      text: 'เกิดข้อผิดพลาดในการโหลดข้อมูล',
      type: 'alert-error'
    }
  }
}

// Find form by ID, handling both string and number comparisons
const form = computed(() => {
  return thaiFratStore.forms.find(f => f.id.toString() === formId.toString())
})

function formatDate(dateString) {
  if (!dateString) return 'ไม่ระบุ'
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('th-TH', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (error) {
    return 'ไม่ระบุ'
  }
}

function getRiskClass(riskLevel) {
  switch (riskLevel) {
    case 'low':
      return 'text-success'
    case 'medium':
      return 'text-warning'
    case 'high':
      return 'text-danger'
    default:
      return ''
  }
}

function editForm() {
  // Navigate to edit form (you might need to create this route)
  router.push({ name: 'thai-frat-form', query: { edit: formId } })
}

async function deleteForm() {
  if (confirm('ต้องการลบข้อมูลนี้ใช่หรือไม่?')) {
    try {
      const success = await thaiFratStore.removeForm(formId)

      if (success) {
        shareMessage.value = { text: 'ลบข้อมูลสำเร็จ', type: 'alert-success' }
        setTimeout(() => {
          router.push('/thai-frat-list')
        }, 1000)
      } else {
        console.error('Delete function returned false - this should not happen with new error handling')
        shareMessage.value = { text: 'เกิดข้อผิดพลาดในการลบข้อมูล', type: 'alert-error' }
      }
    } catch (error) {
      console.error('Error deleting form:', error)

      let errorMessage = 'เกิดข้อผิดพลาดในการลบข้อมูล'

      if (error.message.includes('ไม่มีสิทธิ์')) {
        errorMessage = error.message
      } else if (error.message.includes('HTTP Error')) {
        errorMessage = 'เกิดข้อผิดพลาดจากเซิร์ฟเวอร์ กรุณาลองใหม่อีกครั้ง'
      } else {
        errorMessage = 'เกิดข้อผิดพลาดในการลบข้อมูล: ' + error.message
      }

      shareMessage.value = { text: errorMessage, type: 'alert-error' }
    }

    // Clear message after 3 seconds (only if not successful)
    if (shareMessage.value.type === 'alert-error') {
      setTimeout(() => {
        shareMessage.value = { text: '', type: '' }
      }, 3000)
    }
  }
}

function showShareModal() {
  showShareDialog.value = true
  shareEmail.value = ''
  includePersonalInfo.value = true
}

function closeShareModal() {
  showShareDialog.value = false
  shareEmail.value = ''
  includePersonalInfo.value = true
}

async function shareFormWithUser() {
  if (!shareEmail.value.trim()) {
    shareMessage.value = { text: 'กรุณากรอกอีเมล', type: 'alert-error' }
    setTimeout(() => {
      shareMessage.value = { text: '', type: '' }
    }, 3000)
    return
  }

  sharingInProgress.value = true
  try {
    const baseUrl = getApiBaseUrl()
    const response = await fetch(`${baseUrl}/thai-frat/assessments/${formId}/share`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
      },
      body: JSON.stringify({
        email: shareEmail.value.trim(),
        include_personal_info: includePersonalInfo.value
      })
    })

    if (!response.ok) {
      const error = await response.json()
      shareMessage.value = {
        text: `เกิดข้อผิดพลาด: ${error.error || 'ไม่สามารถแชร์ข้อมูลได้'}`,
        type: 'alert-error'
      }
    } else {
      const data = await response.json()
      shareMessage.value = {
        text: data.message || `แชร์ข้อมูลสำเร็จกับ ${shareEmail.value}`,
        type: 'alert-success'
      }
      closeShareModal()
    }
  } catch (error) {
    console.error('Error sharing form:', error)
    shareMessage.value = {
      text: 'เกิดข้อผิดพลาดในการเชื่อมต่อ backend',
      type: 'alert-error'
    }
  } finally {
    sharingInProgress.value = false
  }

  // Clear message after 3 seconds
  setTimeout(() => {
    shareMessage.value = { text: '', type: '' }
  }, 3000)
}
function goBack() {
  router.back()
}

// Optional: Add method to remove sharing
async function removeShare(username) {
  if (!confirm(`ต้องการยกเลิกการแชร์กับ ${username} ใช่หรือไม่?`)) {
    return
  }

  try {
    const baseUrl = getApiBaseUrl()
    const response = await fetch(`${baseUrl}/thai-frat/assessments/${formId}/share/${username}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
      }
    })

    if (response.ok) {
      const data = await response.json()
      shareMessage.value = {
        text: data.message || `ยกเลิกการแชร์กับ ${username} สำเร็จ`,
        type: 'alert-success'
      }
    } else {
      const error = await response.json()
      shareMessage.value = {
        text: `เกิดข้อผิดพลาด: ${error.error || 'ไม่สามารถยกเลิกการแชร์ได้'}`,
        type: 'alert-error'
      }
    }
  } catch (error) {
    console.error('Error removing share:', error)
    shareMessage.value = {
      text: 'เกิดข้อผิดพลาดในการเชื่อมต่อ backend',
      type: 'alert-error'
    }
  }

  // Clear message after 3 seconds
  setTimeout(() => {
    shareMessage.value = { text: '', type: '' }
  }, 3000)
}
</script>

<style scoped>
.thai-frat-detail {
  max-width: 600px;
  margin: 2rem auto;
  padding: 2rem;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.08);
}

.page-title {
  font-size: 2rem;
  font-weight: 700;
  color: #1a7f37;
  margin-bottom: 2rem;
  text-align: center;
}

.detail-row {
  margin-bottom: 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 1rem;
}

.detail-row:last-of-type {
  border-bottom: none;
}

.detail-row strong {
  color: #1a7f37;
  font-weight: 600;
  min-width: 120px;
  display: inline-block;
}

ul {
  margin: 0.5rem 0 1rem 1.5rem;
  padding: 0;
}

ul li {
  margin-bottom: 0.3rem;
  color: #555;
}

.assessment-details {
  margin: 1rem 0;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.question-item {
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.question-item:last-child {
  margin-bottom: 0;
  border-bottom: none;
  padding-bottom: 0;
}

.question-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.question-header strong {
  color: #1a7f37;
  font-size: 0.95rem;
  flex: 1;
  min-width: 200px;
}

.score-badge {
  background: #1a7f37;
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 15px;
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
}

.question-answer {
  color: #555;
  font-size: 0.9rem;
  line-height: 1.4;
  padding: 0.5rem;
  background: white;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.loading-message {
  text-align: center;
  padding: 3rem 0;
  color: #666;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #1a7f37;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.actions {
  display: flex;
  gap: 1rem;
  margin-top: 2rem;
  flex-wrap: wrap;
}

.btn {
  padding: 0.6rem 1.2rem;
  border-radius: 8px;
  border: none;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(90deg, #1a7f37 0%, #4caf50 100%);
  color: #fff;
}

.btn-primary:hover {
  background: linear-gradient(90deg, #158a2c 0%, #388e3c 100%);
}

.btn-secondary {
  background: #f3f3f3;
  color: #1a7f37;
  border: 1px solid #dbe6e4;
}

.btn-secondary:hover {
  background: #e6ffed;
}

.btn-danger {
  background: #ffe6e6;
  color: #d32f2f;
  border: 1px solid #ffcdd2;
}

.btn-danger:hover {
  background: #ffcdd2;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  pointer-events: none;
}

.text-success {
  color: #1a7f37;
  font-weight: 600;
}

.text-warning {
  color: #f57c00;
  font-weight: 600;
}

.text-danger {
  color: #d32f2f;
  font-weight: 600;
}

.empty-message {
  margin-top: 2rem;
  color: #888;
  text-align: center;
  font-size: 1.1rem;
}

.alert {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 8px;
  text-align: center;
  font-weight: 500;
}

.alert-success {
  background: #e6ffed;
  color: #1a7f37;
  border: 1px solid #c8e6c9;
}

.alert-error {
  background: #ffebee;
  color: #d32f2f;
  border: 1px solid #ffcdd2;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #fff;
  padding: 2rem;
  border-radius: 12px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  position: relative;
  animation: modalFadeIn 0.3s ease-out;
}

@keyframes modalFadeIn {
  from {
    opacity: 0;
    transform: scale(0.9) translateY(-20px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #999;
  cursor: pointer;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: all 0.2s;
}

.modal-close:hover {
  background: #f5f5f5;
  color: #333;
}

.modal-title {
  font-size: 1.3rem;
  font-weight: 600;
  color: #1a7f37;
  margin-bottom: 1.5rem;
  text-align: center;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-label {
  display: block;
  font-weight: 500;
  color: #333;
  margin-bottom: 0.5rem;
}

.form-input {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: #1a7f37;
  box-shadow: 0 0 0 2px rgba(26, 127, 55, 0.1);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  color: #555;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  margin: 0;
}

.modal-actions {
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
  margin-top: 2rem;
}

.modal-actions .btn {
  min-width: 80px;
}

/* Responsive Design */
@media (max-width: 768px) {
  .thai-frat-detail {
    margin: 1rem;
    padding: 1.5rem;
  }

  .page-title {
    font-size: 1.6rem;
  }

  .question-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .question-header strong {
    min-width: auto;
  }

  .score-badge {
    align-self: flex-start;
  }

  .actions {
    flex-direction: column;
  }

  .btn {
    width: 100%;
    text-align: center;
  }

  .modal-content {
    margin: 1rem;
    width: calc(100% - 2rem);
  }

  .modal-actions {
    flex-direction: column;
  }

  .modal-actions .btn {
    width: 100%;
    min-width: auto;
  }
}
</style>
