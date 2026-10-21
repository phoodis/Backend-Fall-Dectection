<template>
  <div class="thai-frat-form card">
    <h2 class="form-title">{{ isEditMode ? 'แก้ไขแบบประเมิน Thai-FRAT' : 'แบบประเมิน Thai-FRAT' }}</h2>
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

  <div class="custom-dropdown" ref="dropdownRef" @click="toggleDropdown">
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
        <strong>ผลประเมิน:</strong> {{ result }} (คะแนนรวม: {{ calculateScore() }})
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">{{ isEditMode ? 'อัปเดตข้อมูล' : 'บันทึกข้อมูล' }}</button>
        <button type="button" class="btn btn-secondary" @click="router.back()">ย้อนกลับ</button>
      </div>
      <div v-if="saveSuccess" class="alert alert-success" style="margin-top:1rem;">บันทึกข้อมูลสำเร็จ!</div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useThaiFratStore } from '@/stores/thaiFrat'

const thaiFratStore = useThaiFratStore()
const router = useRouter()
const route = useRoute()
const isEditMode = ref(false)
const editFormId = ref(null)
const isOpen = ref(false)
const dropdownRef = ref(null)
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

function handleClickOutside(event) {
  if (!isOpen.value) return
  if (dropdownRef.value && !dropdownRef.value.contains(event.target)) {
    isOpen.value = false
  }
}

onMounted(() => {
  if (route.query.edit) {
    isEditMode.value = true
    editFormId.value = route.query.edit

    // ค้นหาข้อมูลจาก store
    const existingForm = thaiFratStore.forms.find(f => f.id.toString() === editFormId.value.toString())
    if (existingForm) {
      form.value = {
        name: existingForm.name,
        tel: existingForm.tel,
        province: existingForm.province || '',
        pdpa: existingForm.pdpa,
        q1: existingForm.q1_score || 0,
        q2: existingForm.q2_score || 0,
        q3: existingForm.q3_score || 0,
        q4: existingForm.q4_score || 0,
        q5: existingForm.q5_score || 0,
        q6: existingForm.q6_score || 0,
      }
      calculateScore()
    }
  }

  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
})

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

// โหลดข้อมูลสำหรับแก้ไข
onMounted(() => {
  if (route.query.edit) {
    isEditMode.value = true
    editFormId.value = route.query.edit

    // ค้นหาข้อมูลจาก store
    const existingForm = thaiFratStore.forms.find(f => f.id.toString() === editFormId.value.toString())
    if (existingForm) {
      form.value = {
        name: existingForm.name,
        tel: existingForm.tel,
        province: existingForm.province || '',
        pdpa: existingForm.pdpa,
        q1: existingForm.q1_score || 0,
        q2: existingForm.q2_score || 0,
        q3: existingForm.q3_score || 0,
        q4: existingForm.q4_score || 0,
        q5: existingForm.q5_score || 0,
        q6: existingForm.q6_score || 0,
      }
      calculateScore()
    }
  }
})

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

async function handleSubmit() {
  saveSuccess.value = false
  const score = calculateScore()

  try {
    if (isEditMode.value && editFormId.value) {
      // โหมดแก้ไข - ส่งไปยัง API
      await thaiFratStore.editForm(editFormId.value, {
        ...form.value,
        q1_score: form.value.q1,
        q2_score: form.value.q2,
        q3_score: form.value.q3,
        q4_score: form.value.q4,
        q5_score: form.value.q5,
        q6_score: form.value.q6,
      })
      saveSuccess.value = true
      setTimeout(() => {
        router.push(`/thai-frat-detail/${editFormId.value}`)
      }, 1200)
    } else {
      // โหมดสร้างใหม่
      thaiFratStore.addForm({ ...form.value, score })
      saveSuccess.value = true
      setTimeout(() => {
        router.push('/thai-frat-list')
      }, 1200)
    }
  } catch (error) {
    console.error('Error in handleSubmit:', error)
    alert('เกิดข้อผิดพลาด: ' + (error.message || 'ไม่ทราบสาเหตุ'))
  }
}
</script>

<style scoped>
.thai-frat-form {
  max-width: 600px;
  margin: 0 auto;
  padding: 2rem;
}
.form-group {
  margin-bottom: 1.5rem;
}
.alert {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 6px;
}
.alert-success {
  background: #e6ffed;
  color: #1a7f37;
}
.alert-warning {
  background: #fffbe6;
  color: #b26a00;
}
.alert-danger {
  background: #ffe6e6;
  color: #d32f2f;
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
