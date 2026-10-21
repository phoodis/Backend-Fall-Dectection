<template>
  <div class="thai-frat-list card">
    <h1 class="page-title">ข้อมูล Thai-FRAT</h1>
    <div class="actions">
      <input v-model="searchQuery" placeholder="ค้นหาชื่อ/เบอร์/จังหวัด/คะแนน/ความเสี่ยง/PDPA" class="form-input" />
    </div>

    <!-- ฟอร์มกรอกข้อมูล Thai-FRAT -->
    <div v-if="!searchQuery.trim()" class="thai-frat-form card" style="margin-bottom:2rem;">
      <h2 class="form-title" style="color:#1a7f37;">เพิ่มข้อมูล Thai-FRAT</h2>
      <form @submit.prevent="handleSubmit" class="form-content">
        <div class="form-group">
          <label class="form-label">ชื่อ-นามสกุล</label>
          <input v-model="form.name" class="form-input" type="text" required placeholder="กรอกชื่อ-นามสกุล" />
        </div>
        <div class="form-group">
          <label class="form-label">เบอร์โทรศัพท์</label>
          <input v-model="form.tel" class="form-input" type="tel" required placeholder="กรอกเบอร์โทรศัพท์" />
        </div>
    <!-- เปลี่ยนเป็น dropdown เลือกทุกจังหวัดในประเทศไทย -->
<div class="form-group">
  <label class="form-label">จังหวัด</label>

  <div class="custom-dropdown" @click="toggleDropdown">
    <div class="dropdown-selected">
      {{ form.province || '-- กรุณาเลือกจังหวัด --' }}
    </div>

    <div v-if="isOpen" class="dropdown-menu">
      <div
        v-for="province in provinces"
        :key="province"
        class="dropdown-item"
        @click.stop="selectProvince(province)"
      >
        {{ province }}
      </div>
    </div>
  </div>
</div>
        <div class="form-group pdpa-group">
          <input v-model="form.pdpa" type="checkbox" id="pdpa" required />
          <label for="pdpa" class="pdpa-label">ยินยอมให้เก็บข้อมูลตาม PDPA</label>
        </div>
        <div class="form-group">
          <label class="form-label">คะแนนประเมิน (แต่ละข้อ)</label>
          <div class="score-inputs">
            <div class="score-item">
              <label>1. ประวัติการพลัดตกหกล้ม</label>
              <select v-model.number="form.q1" class="form-input" required>
                <option :value="25">เคย (25 คะแนน)</option>
                <option :value="0">ไม่เคย (0 คะแนน)</option>
              </select>
            </div>
            <div class="score-item">
              <label>2. มีการวินิจฉัยโรคมากกว่า 1 รายการ</label>
              <select v-model.number="form.q2" class="form-input" required>
                <option :value="0">ไม่ใช่ (0 คะแนน)</option>
                <option :value="15">ใช่ (15 คะแนน)</option>
              </select>
            </div>
            <div class="score-item">
              <label>3. การช่วยในการเคลื่อนย้าย</label>
              <select v-model.number="form.q3" class="form-input" required>
                <option :value="0">เดินเอง/รถเข็น/นอนพัก/บุคลากรช่วย (0 คะแนน)</option>
                <option :value="15">ไม้ค้ำยัน/ไม้เท้า/Walker (15 คะแนน)</option>
                <option :value="30">เดินโดยยึดเกาะเฟอร์นิเจอร์ (30 คะแนน)</option>
              </select>
            </div>
            <div class="score-item">
              <label>4. ให้สารละลายทางหลอดเลือดดำ (IV) / ใช้ Heparin lock</label>
              <select v-model.number="form.q4" class="form-input" required>
                <option :value="25">ใช่ (25 คะแนน)</option>
                <option :value="0">ไม่มี (0 คะแนน)</option>
              </select>
            </div>
            <div class="score-item">
              <label>5. การเดิน / การเคลื่อนย้าย</label>
              <select v-model.number="form.q5" class="form-input" required>
                <option :value="0">ปกติ/นอนพัก/ไม่เคลื่อนไหว (0 คะแนน)</option>
                <option :value="10">อ่อนแรง/เดินก้มตัว/ก้าวสั้น (10 คะแนน)</option>
                <option :value="20">มีความพร่อง/ต้องช่วยเหลือ (20 คะแนน)</option>
              </select>
            </div>
            <div class="score-item">
              <label>6. สภาพจิตใจ</label>
              <select v-model.number="form.q6" class="form-input" required>
                <option :value="0">รับรู้ตนเอง (0 คะแนน)</option>
                <option :value="15">ลืมข้อจำกัด (15 คะแนน)</option>
              </select>
            </div>
          </div>
        </div>
        <div v-if="result" :class="['alert', resultClass]" style="margin-bottom:1rem;">
          <strong>ผลประเมิน:</strong> {{ result }}
          <div class="score-summary">
            <span class="total-score">คะแนนรวม: {{ calculateScore() }}</span>
            <span class="risk-badge" :class="getRiskBadgeClass(calculateScore())">
              {{ getRiskLevel(calculateScore()) }}
            </span>
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">บันทึกข้อมูล</button>
        </div>
        <div v-if="saveSuccess" class="alert alert-success" style="margin-top:1rem;">บันทึกข้อมูลสำเร็จ!</div>
      </form>
    </div>

    <div v-if="filteredForms.length === 0" class="empty-message">ไม่พบข้อมูล</div>
    <table v-if="filteredForms.length > 0" class="data-table">
      <thead>
        <tr>
          <th>ชื่อ-นามสกุล</th>
          <th>เบอร์โทร</th>
          <th>จังหวัด</th>
          <th>คะแนน</th>
          <th>ระดับความเสี่ยง</th>
          <th>PDPA</th>
          <th>ดูรายละเอียด</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="form in filteredForms" :key="form.id">
          <td>{{ form.name }}</td>
          <td>{{ form.tel || 'ไม่ระบุ' }}</td>
          <td>{{ form.province || 'ไม่ระบุ' }}</td>
          <td>
            <span class="score-display">{{ form.score }}</span>
          </td>
          <td>
            <span class="risk-badge" :class="getTableRiskClass(form.risk_level || form.score)">
              {{ getTableRiskText(form.risk_level || form.score) }}
            </span>
          </td>
          <td><span :class="form.pdpa ? 'text-success' : 'text-danger'">{{ form.pdpa ? 'ยินยอม' : 'ไม่ยินยอม' }}</span></td>
          <td>
            <router-link :to="{ name: 'ThaiFratDetail', params: { id: form.id } }" class="btn btn-sm btn-info">ดูรายละเอียด</router-link>
          </td>
        </tr>
      </tbody>
    </table>
    <!-- ...existing code... -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useThaiFratStore } from '@/stores/thaiFrat'
import { getApiBaseUrl } from '@/config/api'

const thaiFratStore = useThaiFratStore()
const searchQuery = ref('')
const shareMessage = ref('')
const router = useRouter()
const isOpen = ref(false)

// ...existing code...

// ฟอร์มกรอกข้อมูล Thai-FRAT
import { nextTick } from 'vue'
const form = ref({
  name: '',
  tel: '',
  province: '',
  pdpa: false,
  q1: 0,
  q2: 0,
  q3: 0,
  q4: 0,
  q5: 0,
  q6: 0,
})

function toggleDropdown() {
  isOpen.value = !isOpen.value
}

function selectProvince(province) {
  form.value.province = province
  isOpen.value = false
}

const provinces = ref([
  'กรุงเทพมหานคร',
  'กระบี่',
  'กาญจนบุรี',
  'กาฬสินธุ์',
  'กำแพงเพชร',
  'ขอนแก่น',
  'จันทบุรี',
  'ฉะเชิงเทรา',
  'ชลบุรี',
  'ชัยนาท',
  'ชัยภูมิ',
  'ชุมพร',
  'เชียงราย',
  'เชียงใหม่',
  'ตรัง',
  'ตราด',
  'ตาก',
  'นครนายก',
  'นครปฐม',
  'นครพนม',
  'นครราชสีมา',
  'นครศรีธรรมราช',
  'นครสวรรค์',
  'นนทบุรี',
  'นราธิวาส',
  'น่าน',
  'บึงกาฬ',
  'บุรีรัมย์',
  'ปทุมธานี',
  'ประจวบคีรีขันธ์',
  'ปราจีนบุรี',
  'ปัตตานี',
  'พระนครศรีอยุธยา',
  'พะเยา',
  'พังงา',
  'พัทลุง',
  'พิจิตร',
  'พิษณุโลก',
  'เพชรบุรี',
  'เพชรบูรณ์',
  'แพร่',
  'ภูเก็ต',
  'มหาสารคาม',
  'มุกดาหาร',
  'แม่ฮ่องสอน',
  'ยโสธร',
  'ยะลา',
  'ร้อยเอ็ด',
  'ระนอง',
  'ระยอง',
  'ราชบุรี',
  'ลพบุรี',
  'ลำปาง',
  'ลำพูน',
  'เลย',
  'ศรีสะเกษ',
  'สกลนคร',
  'สงขลา',
  'สตูล',
  'สมุทรปราการ',
  'สมุทรสงคราม',
  'สมุทรสาคร',
  'สระแก้ว',
  'สระบุรี',
  'สิงห์บุรี',
  'สุโขทัย',
  'สุพรรณบุรี',
  'สุราษฎร์ธานี',
  'สุรินทร์',
  'หนองคาย',
  'หนองบัวลำภู',
  'อ่างทอง',
  'อำนาจเจริญ',
  'อุดรธานี',
  'อุตรดิตถ์',
  'อุทัยธานี',
  'อุบลราชธานี'
])
const result = ref('')
const resultClass = ref('')
const saveSuccess = ref(false)

// Edit modal variables
const editingForm = ref({})
const showEditModal = ref(false)

function calculateScore() {
  const score = form.value.q1 + form.value.q2 + form.value.q3 + form.value.q4 + form.value.q5 + form.value.q6
  if (score >= 51) {
    result.value = 'มีความเสี่ยงสูง (ควรเฝ้าระวังและปรับสภาพแวดล้อม)'
    resultClass.value = 'alert-danger'
  } else if (score >= 25) {
    result.value = 'มีความเสี่ยง (ควรระวังการลื่น/ตก/หกล้ม)'
    resultClass.value = 'alert-warning'
  } else {
    result.value = 'ไม่มีความเสี่ยง หรือมีความเสี่ยงต่ำ'
    resultClass.value = 'alert-success'
  }
  return score
}

function getRiskLevel(score) {
  if (score >= 51) return 'HIGH RISK'
  if (score >= 25) return 'MEDIUM RISK'
  return 'LOW RISK'
}

function getRiskBadgeClass(score) {
  if (score >= 51) return 'risk-high'
  if (score >= 25) return 'risk-medium'
  return 'risk-low'
}

function getTableRiskClass(riskLevelOrScore) {
  if (typeof riskLevelOrScore === 'string') {
    switch (riskLevelOrScore) {
      case 'high': return 'risk-high'
      case 'medium': return 'risk-medium'
      case 'low': return 'risk-low'
      default: return 'risk-low'
    }
  } else {
    const score = riskLevelOrScore
    if (score >= 51) return 'risk-high'
    if (score >= 25) return 'risk-medium'
    return 'risk-low'
  }
}

function getTableRiskText(riskLevelOrScore) {
  if (typeof riskLevelOrScore === 'string') {
    switch (riskLevelOrScore) {
      case 'high': return 'สูง'
      case 'medium': return 'กลาง'
      case 'low': return 'ต่ำ'
      default: return 'ต่ำ'
    }
  } else {
    const score = riskLevelOrScore
    if (score >= 51) return 'สูง'
    if (score >= 25) return 'กลาง'
    return 'ต่ำ'
  }
}

async function handleSubmit() {
  saveSuccess.value = false
  const score = calculateScore()

  // เตรียมข้อมูลตาม API documentation
  const payload = {
    name: form.value.name,
    tel: form.value.tel,
    province: form.value.province,
    pdpa_consent: form.value.pdpa,
    q1: form.value.q1,
    q2: form.value.q2,
    q3: form.value.q3,
    q4: form.value.q4,
    q5: form.value.q5,
    q6: form.value.q6
  }

  try {
    const baseUrl = getApiBaseUrl()
    const res = await fetch(`${baseUrl}/thai-frat/assessments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
      },
      body: JSON.stringify(payload)
    })

    if (!res.ok) {
      const error = await res.json()
      alert('เกิดข้อผิดพลาด: ' + (error.error || 'ไม่สามารถบันทึกข้อมูลได้'))
      return
    }

    const data = await res.json()
    saveSuccess.value = true

    // แปลงข้อมูลจาก API response ให้เข้ากับ store format
    const assessmentForStore = {
      id: data.assessment.id,
      name: data.assessment.name,
      tel: data.assessment.tel,
      province: data.assessment.province || form.value.province,
      pdpa: data.assessment.pdpa_consent,
      score: data.assessment.total_score,
      risk_level: data.assessment.risk_level,
      risk_description: data.assessment.risk_description,
      q1_score: data.assessment.q1_score,
      q1_value: data.assessment.q1_value,
      q2_score: data.assessment.q2_score,
      q2_value: data.assessment.q2_value,
      q3_score: data.assessment.q3_score,
      q3_value: data.assessment.q3_value,
      q4_score: data.assessment.q4_score,
      q4_value: data.assessment.q4_value,
      q5_score: data.assessment.q5_score,
      q5_value: data.assessment.q5_value,
      q6_score: data.assessment.q6_score,
      q6_value: data.assessment.q6_value,
      created_at: data.assessment.created_at,
      updated_at: data.assessment.updated_at,
      creator_username: data.assessment.creator_username,
      is_own: true
    }

    // เพิ่มข้อมูลใหม่ใน store
    thaiFratStore.addForm(assessmentForStore)

    nextTick(() => {
      form.value = {
        name: '',
        tel: '',
        province: '',
        pdpa: false,
        q1: 0,
        q2: 0,
        q3: 0,
        q4: 0,
        q5: 0,
        q6: 0,
      }
      result.value = ''
      resultClass.value = ''
    })

    setTimeout(() => {
      saveSuccess.value = false
    }, 1200)
  } catch (err) {
    console.error('Network error:', err)
    alert('เกิดข้อผิดพลาดในการเชื่อมต่อ backend')
  }
}

onMounted(async () => {
  try {
    await thaiFratStore.loadForms()
  } catch (error) {
    console.error('Error loading forms:', error)
  }
})

const filteredForms = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return thaiFratStore.forms
  return thaiFratStore.forms.filter(form => {
    const name = (form.name || '').toLowerCase()
    const tel = (form.tel || '').toLowerCase()
    const province = (form.province || '').toLowerCase()
    const score = String(form.score || '').toLowerCase()
    const pdpa = form.pdpa ? 'ยินยอม' : 'ไม่ยินยอม'
    const riskDescription = (form.risk_description || '').toLowerCase()
    const riskLevel = getTableRiskText(form.risk_level || form.score).toLowerCase()
    return (
      name.includes(query) ||
      tel.includes(query) ||
      province.includes(query) ||
      score.includes(query) ||
      pdpa.includes(query) ||
      riskDescription.includes(query) ||
      riskLevel.includes(query)
    )
  })
})

function goToForm() {
  router.push('/thai-frat-form')
}

function share(form) {
  navigator.clipboard.writeText(JSON.stringify(form, null, 2))
  shareMessage.value = 'คัดลอกข้อมูลสำเร็จ!'
  setTimeout(() => (shareMessage.value = ''), 2000)
}

function startEditForm(form) {
  editingForm.value = { ...form }
  showEditModal.value = true
}

async function saveEditForm() {
  // Validation เบอร์โทร
  const telPattern = /^0[0-9]{8,9}$/
  if (editingForm.value.tel && !telPattern.test(editingForm.value.tel)) {
    alert('กรุณากรอกเบอร์โทรที่ถูกต้อง')
    return
  }
  // Validation คะแนน
  if (editingForm.value.score < 0 || editingForm.value.score > 100) {
    alert('คะแนนต้องอยู่ระหว่าง 0-100')
    return
  }

  try {
    const success = await thaiFratStore.editForm(editingForm.value.id, editingForm.value)
    if (success) {
      showEditModal.value = false
      alert('แก้ไขข้อมูลสำเร็จ')
      // Refresh the data to show updated information
      await thaiFratStore.loadForms()
    } else {
      alert('เกิดข้อผิดพลาดในการแก้ไขข้อมูล')
    }
  } catch (error) {
    console.error('Error updating form:', error)
    alert('เกิดข้อผิดพลาดในการเชื่อมต่อ backend')
  }
}

function cancelEdit() {
  showEditModal.value = false
}
</script>

<style scoped>

.thai-frat-list {
  max-width: 900px;
  margin: 2rem auto;
  padding: 2.5rem 2rem;
  background: #fff;
  border-radius: 18px;
  box-shadow: 0 4px 32px rgba(0,0,0,0.10);
}
.page-title {
  font-size: 2.2rem;
  font-weight: 700;
  color: #1a7f37;
  margin-bottom: 2rem;
  text-align: center;
}
.actions {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  align-items: center;
}
.form-input {
  padding: 0.6rem 1rem;
  border-radius: 8px;
  border: 1px solid #dbe6e4;
  font-size: 1rem;
  background: #f8fafc;
  transition: border-color 0.2s;
}
.form-input:focus {
  border-color: #1a7f37;
  outline: none;
}
.btn {
  padding: 0.5rem 1.2rem;
  border-radius: 8px;
  border: none;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
  box-shadow: 0 2px 8px rgba(26,127,55,0.05);
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
.btn-info {
  background: #e3f2fd;
  color: #1976d2;
  border: 1px solid #90caf9;
}
.btn-info:hover {
  background: #bbdefb;
}
.btn-danger {
  background: #ffe6e6;
  color: #d32f2f;
  border: 1px solid #ffcdd2;
}
.btn-danger:hover {
  background: #ffcdd2;
}
.btn-sm {
  font-size: 0.95rem;
  padding: 0.35rem 0.8rem;
}
.data-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: #f8fafc;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(26,127,55,0.04);
  overflow: hidden;
}
.data-table th {
  background: #e6ffed;
  color: #1a7f37;
  font-weight: 600;
  padding: 0.8rem 1rem;
  border-bottom: 2px solid #dbe6e4;
}
.data-table td {
  padding: 0.7rem 1rem;
  border-bottom: 1px solid #e0e0e0;
  background: #fff;
}
.data-table tr:hover td {
  background: #f3f3f3;
}

.score-display {
  font-weight: 600;
  font-size: 1.1rem;
  color: #1a7f37;
}

.data-table .risk-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.empty-message {
  margin-top: 2rem;
  color: #bdbdbd;
  text-align: center;
  font-size: 1.1rem;
}
.alert {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 8px;
  background: #e6ffed;
  color: #1a7f37;
  font-weight: 500;
  text-align: center;
  box-shadow: 0 2px 8px rgba(26,127,55,0.07);
}

.alert-success {
  background: #e6ffed;
  color: #1a7f37;
  border: 1px solid #c8e6c9;
}

.alert-warning {
  background: #fff3e0;
  color: #f57c00;
  border: 1px solid #ffcc02;
}

.alert-danger {
  background: #ffebee;
  color: #d32f2f;
  border: 1px solid #ffcdd2;
}

.score-summary {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
  flex-wrap: wrap;
}

.total-score {
  font-size: 1.1rem;
  font-weight: 600;
}

.risk-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 15px;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.risk-low {
  background: #4caf50;
  color: white;
}

.risk-medium {
  background: #ff9800;
  color: white;
}

.risk-high {
  background: #f44336;
  color: white;
}
.text-success {
  color: #1a7f37;
  font-weight: 600;
}
.text-danger {
  color: #d32f2f;
  font-weight: 600;
}
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0,0,0,0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-content {
  background: #fff;
  padding: 2.5rem 2rem;
  border-radius: 16px;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 4px 32px rgba(26,127,55,0.12);
  position: relative;
  animation: modalFadeIn 0.3s;
}
@keyframes modalFadeIn {
  from { opacity: 0; transform: translateY(30px); }
  to { opacity: 1; transform: translateY(0); }
}
.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: none;
  border: none;
  font-size: 2rem;
  color: #bdbdbd;
  cursor: pointer;
  z-index: 10;
  transition: color 0.2s;
}
.modal-close:hover {
  color: #d32f2f;
}
.form-group label {
  font-weight: 500;
  color: #388e3c;
  margin-bottom: 0.3rem;
  display: block;
}
.form-group {
  margin-bottom: 1.2rem;
}
.pdpa-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 1.5rem 0;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.pdpa-label {
  font-size: 0.95rem;
  color: #555;
  cursor: pointer;
  margin: 0;
}
.score-inputs {
  display: grid;
  gap: 1rem;
  margin-top: 0.5rem;
}
.score-item {
  padding: 1rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.score-item label {
  font-size: 0.9rem;
  font-weight: 500;
  color: #333;
  margin-bottom: 0.5rem;
  display: block;
  line-height: 1.4;
}
.form-actions {
  margin-top: 2rem;
  text-align: center;
}
.form-title {
  margin-bottom: 1.5rem;
  font-size: 1.5rem;
  font-weight: 600;
}
.thai-frat-form {
  background: #fff;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 2px 16px rgba(26,127,55,0.05);
  border: 1px solid #e6ffed;
}
.actions .btn {
  min-width: 110px;
}

/* Responsive Design */
@media (max-width: 768px) {
  .thai-frat-list {
    margin: 1rem;
    padding: 1.5rem;
  }

  .page-title {
    font-size: 1.8rem;
  }

  .thai-frat-form {
    padding: 1.5rem;
  }

  .score-inputs {
    gap: 0.8rem;
  }

  .score-item {
    padding: 0.8rem;
  }

  .data-table {
    font-size: 0.9rem;
  }

  .data-table th,
  .data-table td {
    padding: 0.5rem 0.7rem;
  }

  .score-summary {
    flex-direction: column;
    gap: 0.5rem;
  }

  .actions {
    flex-direction: column;
    align-items: stretch;
  }

  .form-input {
    width: 100%;
  }
}

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .province-dropdown {
    font-size: 0.95rem;
    max-height: 180px;
  }
}

@media (max-width: 480px) {
  .province-dropdown {
    font-size: 0.9rem;
    max-height: 150px;
  }
}

.custom-dropdown {
  position: relative;
  cursor: pointer;
}

.dropdown-selected {
  padding: 0.6rem 1rem;
  border: 1px solid #dbe6e4;
  border-radius: 10px;
  background: #f8fafc;
}

.dropdown-menu {
  position: absolute;
  top: 110%;
  left: 0;
  width: 100%;
  max-height: 200px; /* 🔥 จำกัดความสูง */
  overflow-y: auto;
  background: #fff;
  border: 1px solid #dbe6e4;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(0,0,0,0.1);
  z-index: 999;
}

.dropdown-item {
  padding: 0.6rem 1rem;
  transition: 0.2s;
}

.dropdown-item:hover {
  background: #e6ffed;
}
</style>
