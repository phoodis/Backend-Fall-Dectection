/**
 * Thai-FRAT Assessment API Service
 */
import { getApiBaseUrl, API_ENDPOINTS } from '@/config/api'

function getAuthToken() {
  return localStorage.getItem('authToken')
}

export default {
  /**
   * GET /api/thai-frat/assessments
   * Get all assessments for current user (own + shared)
   */
  async getAllAssessments() {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.BASE}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!response.ok) throw new Error('Failed to fetch assessments')
    return await response.json()
  },

  /**
   * POST /api/thai-frat/assessments
   * Create a new assessment
   */
  async createAssessment(data) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.BASE}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.error || 'Failed to create assessment')
    }
    return await response.json()
  },

  /**
   * GET /api/thai-frat/assessments/{assessment_id}
   */
  async getAssessment(id) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.DETAIL(id)}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!response.ok) throw new Error('Assessment not found or access denied')
    return await response.json()
  },

  /**
   * PUT /api/thai-frat/assessments/{assessment_id}
   */
  async updateAssessment(id, data) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.DETAIL(id)}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.error || 'Failed to update assessment')
    }
    return await response.json()
  },

  /**
   * DELETE /api/thai-frat/assessments/{assessment_id}
   */
  async deleteAssessment(id) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.DETAIL(id)}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.error || 'Failed to delete assessment')
    }
    return await response.json()
  },

  /**
   * POST /api/thai-frat/assessments/{assessment_id}/share
   */
  async shareAssessment(id, username, includePersonalInfo = true) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.SHARE(id)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ username, include_personal_info: includePersonalInfo }),
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.error || 'Failed to share assessment')
    }
    return await response.json()
  },

  /**
   * DELETE /api/thai-frat/assessments/{assessment_id}/share/{username}
   */
  async unshareAssessment(id, username) {
    const token = getAuthToken()
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.DELETESHARE(id, username)}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.error || 'Failed to unshare assessment')
    }
    return await response.json()
  },

  /**
   * GET /api/thai-frat/question-options
   */
  async getQuestionOptions() {
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.ASSIGNMENTS.OPTION}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    })
    if (!response.ok) throw new Error('Failed to fetch question options')
    return await response.json()
  },
}
