import { getApiBaseUrl, API_ENDPOINTS } from '@/config/api'

function getAuthToken() {
  return localStorage.getItem('authToken')
}

async function get(path) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${getAuthToken()}`
    },
  })
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  return response.json()
}

export default {
  // The backend paginates and filters server-side, so the page passes both through rather
  // than fetching everything and filtering in the browser -- this table grows without limit.
  fetchSystemLogs: ({ page = 1, perPage = 50, level = '', component = '' } = {}) => {
    const params = new URLSearchParams({ page, per_page: perPage })
    if (level) params.set('level', level)
    if (component) params.set('component', component)
    return get(`${API_ENDPOINTS.SYSTEM_LOGS.BASE}?${params.toString()}`)
  },

  fetchLevels: () => get(API_ENDPOINTS.SYSTEM_LOGS.LEVELS),
  fetchComponents: () => get(API_ENDPOINTS.SYSTEM_LOGS.COMPONENTS),
}
