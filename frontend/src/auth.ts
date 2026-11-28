import { computed, reactive, readonly, ref } from 'vue'
import { api, ApiError } from './api'
import { HttpApi } from './api/http'
import { getAccessToken, setAccessToken } from './api/session'
import type { User } from './types'

const token = ref<string | null>(getAccessToken())
const user = ref<User | null>(null)
const initialized = ref(false)
const sessionExpired = ref(false)
let sessionRevision = 0
let loginRevision = 0
let restoreRequest: Promise<void> | undefined

export const auth = readonly(
  reactive({
    token,
    user,
    initialized,
    sessionExpired,
    isAuthenticated: computed(() => token.value !== null && user.value !== null),
    isResearcher: computed(() => user.value?.role === 'researcher'),
    isEnterprise: computed(() => user.value?.role === 'enterprise'),
  }),
)

export async function login(username: string, password: string) {
  const attempt = ++loginRevision
  const response = await api.login(username, password)
  if (attempt === loginRevision) {
    sessionRevision++
    token.value = response.data.token
    setAccessToken(token.value)
    user.value = response.data.user
    sessionExpired.value = false
    initialized.value = true
  }
  return response.data.user
}

export function restoreSession(): Promise<void> {
  if (initialized.value) return Promise.resolve()
  if (!token.value) {
    initialized.value = true
    return Promise.resolve()
  }
  const attempt = sessionRevision
  restoreRequest ??= api
    .me()
    .then(({ data }) => {
      if (attempt === sessionRevision) user.value = data
    })
    .catch((error: unknown) => {
      if (attempt === sessionRevision) {
        clearSession(error instanceof ApiError && error.httpStatus === 401)
      }
    })
    .finally(() => {
      if (attempt === sessionRevision) initialized.value = true
      restoreRequest = undefined
    })
  return restoreRequest
}

export function logout() {
  loginRevision++
  clearSession()
}

function clearSession(expired = false) {
  sessionRevision++
  setAccessToken(null)
  sessionExpired.value = expired
  token.value = null
  user.value = null
  initialized.value = true
}

if (api instanceof HttpApi) {
  api.onUnauthorized((requestToken) => {
    if (requestToken && requestToken === token.value) clearSession(true)
  })
}
