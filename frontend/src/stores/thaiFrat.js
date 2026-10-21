import { ref } from 'vue'
import { defineStore } from 'pinia'
import { getApiBaseUrl } from '@/config/api'

export const useThaiFratStore = defineStore('thaiFrat', () => {
  const forms = ref([])

  function addForm(form) {
    // Check if form already exists to prevent duplicates
    const existingIndex = forms.value.findIndex(f => f.id.toString() === form.id.toString())
    if (existingIndex !== -1) {
      // Update existing form
      forms.value[existingIndex] = { ...form }
    } else {
      // Add new form
      forms.value.push({ ...form })
    }
    return true
  }

  async function loadForms() {
    try {
      const baseUrl = getApiBaseUrl()
      const response = await fetch(`${baseUrl}/thai-frat/assessments`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
        }
      })

      if (!response.ok) {
        console.error('Failed to load assessments:', response.status)
        // Fallback to localStorage for offline support
        const saved = localStorage.getItem('thaiFratForms')
        if (saved) {
          const arr = JSON.parse(saved)
          if (Array.isArray(arr)) forms.value = arr
        }
        return
      }

      const data = await response.json()
      const allAssessments = []

      // รวมข้อมูลจาก own_assessments
      if (data.own_assessments && Array.isArray(data.own_assessments)) {
        data.own_assessments.forEach(assessment => {
          allAssessments.push({
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
            is_own: true
          })
        })
      }

      // รวมข้อมูลจาก shared_assessments
      if (data.shared_assessments && Array.isArray(data.shared_assessments)) {
        data.shared_assessments.forEach(shared => {
          const assessment = shared.assessment
          allAssessments.push({
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
            is_own: false,
            shared_by: shared.share_info.shared_by_username,
            include_personal_info: shared.share_info.include_personal_info
          })
        })
      }

      forms.value = allAssessments
    } catch (error) {
      console.error('Error loading forms:', error)
      // Fallback to localStorage for offline support
      try {
        const saved = localStorage.getItem('thaiFratForms')
        if (saved) {
          const arr = JSON.parse(saved)
          if (Array.isArray(arr)) forms.value = arr
        }
      } catch (e) {
        forms.value = []
      }
    }
  }

  function searchForms(query) {
    if (!query) return forms.value
    const q = query.trim().toLowerCase()
    return forms.value.filter(f =>
      (f.name && f.name.toLowerCase().includes(q)) ||
      (f.tel && f.tel.toLowerCase().includes(q)) ||
      (f.province && f.province.toLowerCase().includes(q)) ||
      (f.score && f.score.toString().toLowerCase().includes(q)) ||
      (f.risk_description && f.risk_description.toLowerCase().includes(q))
    )
  }

  function shareForm(id) {
    const form = forms.value.find(f => f.id === id)
    if (!form) return null
    // ตัวอย่าง: return ข้อมูลสำหรับแชร์
    return JSON.stringify(form, null, 2)
  }

  async function removeForm(id) {
    try {
      const baseUrl = getApiBaseUrl()
      const response = await fetch(`${baseUrl}/thai-frat/assessments/${id}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
        }
      })

      // Check specific status codes
      if (response.status === 200) {
        // Success - process the response
        try {
          const responseData = await response.json()
          console.log('Delete successful:', responseData)
        } catch (jsonError) {
          console.log('Delete successful, but no JSON response body')
        }

        // Remove from local store - use string comparison for ID
        const idx = forms.value.findIndex(f => f.id.toString() === id.toString())
        if (idx !== -1) {
          forms.value.splice(idx, 1)
          console.log('Removed from local store at index:', idx)
        } else {
          console.warn('Item not found in local store, but API deletion successful')
        }
        return true

      } else if (response.status === 404) {
        console.warn('Assessment not found (404), but treating as successful deletion')
        // Remove from local store anyway
        const idx = forms.value.findIndex(f => f.id.toString() === id.toString())
        if (idx !== -1) {
          forms.value.splice(idx, 1)
        }
        return true

      } else if (response.status === 403) {
        console.error('Access denied (403) - insufficient permissions to delete')
        const errorData = await response.json().catch(() => ({ error: 'Access denied' }))
        throw new Error(errorData.error || 'ไม่มีสิทธิ์ในการลบข้อมูลนี้')

      } else {
        console.error('Failed to delete assessment:', response.status)
        const errorData = await response.json().catch(() => ({}))
        console.error('Delete error details:', errorData)
        throw new Error(errorData.error || `HTTP Error ${response.status}`)
      }

    } catch (error) {
      console.error('Error deleting form:', error)
      // Re-throw the error so the calling function can handle it
      throw error
    }
  }

  // ฟังก์ชันแก้ไขฟอร์ม
  async function editForm(id, updatedForm) {
    try {
      const payload = {
        name: updatedForm.name,
        tel: updatedForm.tel,
        province: updatedForm.province,
        pdpa_consent: updatedForm.pdpa,
        q1: updatedForm.q1_score || 0,
        q2: updatedForm.q2_score || 0,
        q3: updatedForm.q3_score || 0,
        q4: updatedForm.q4_score || 0,
        q5: updatedForm.q5_score || 0,
        q6: updatedForm.q6_score || 0
      }

      const baseUrl = getApiBaseUrl()
      const response = await fetch(`${baseUrl}/thai-frat/assessments/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || '')
        },
        body: JSON.stringify(payload)
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        console.error('Failed to update assessment:', response.status, errorData)
        throw new Error(errorData.error || `HTTP Error ${response.status}`)
      }

      const data = await response.json()

      // Update local store
      const idx = forms.value.findIndex(f => f.id.toString() === id.toString())
      if (idx !== -1) {
        forms.value[idx] = {
          ...forms.value[idx],
          name: data.assessment.name,
          tel: data.assessment.tel,
          province: data.assessment.province,
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
          updated_at: data.assessment.updated_at
        }
        return true
      }
      throw new Error('Assessment not found in store')
    } catch (error) {
      console.error('Error updating form:', error)
      throw error
    }
  }

  return { forms, addForm, loadForms, searchForms, shareForm, removeForm, editForm }
})
