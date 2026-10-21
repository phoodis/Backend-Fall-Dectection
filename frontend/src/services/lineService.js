import { getApiBaseUrl, API_ENDPOINTS } from '@/config/api'

function getAuthToken() {
  return localStorage.getItem('authToken')
}

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getAuthToken()}`
  }
}

// The backend answers with { success, error } on failures, and that error text is the only
// thing that explains a rejected token or a disabled switch -- surface it instead of a
// generic "request failed".
async function parse(response) {
  // This backend has no /line/* routes until the LINE step: say so, so the page can show a notice
  // instead of an error.
  if (response.status === 404) {
    const unavailable = new Error('LINE notifications are not enabled on this server')
    unavailable.unavailable = true
    throw unavailable
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.success === false) {
    throw new Error(data.error || 'LINE request failed')
  }
  return data
}

export default {
  fetchLineSettings: async () => {
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.LINE.SETTINGS}`, {
      method: 'GET',
      headers: authHeaders(),
    })
    return parse(response)
  },

  updateLineSettings: async (settings) => {
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.LINE.SETTINGS}`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(settings),
    })
    return parse(response)
  },

  testLineSettings: async () => {
    const response = await fetch(`${getApiBaseUrl()}${API_ENDPOINTS.LINE.TEST}`, {
      method: 'POST',
      headers: authHeaders(),
    })
    return parse(response)
  },
}
