const TOKEN_KEY = 'aim_access_token'
let memoryToken: string | null = null
let storageUnavailable = false

export function browserSessionStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.sessionStorage
  } catch {
    return undefined
  }
}

export function getAccessToken(): string | null {
  if (storageUnavailable) return memoryToken
  try {
    const storage = browserSessionStorage()
    return storage ? storage.getItem(TOKEN_KEY) : memoryToken
  } catch {
    return memoryToken
  }
}

export function setAccessToken(token: string | null) {
  memoryToken = token
  if (storageUnavailable) return
  try {
    const storage = browserSessionStorage()
    if (token === null) storage?.removeItem(TOKEN_KEY)
    else storage?.setItem(TOKEN_KEY, token)
  } catch {
    storageUnavailable = true
  }
}
