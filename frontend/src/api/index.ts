import { MockApi } from '../mock/api'
import { HttpApi } from './http'
import { getAccessToken } from './session'
import type { ApiClient } from './types'

export { isContactRevealed, normalizeIntentContact } from './contact'
export { ApiError } from './error'
export type {
  AchievementListParams,
  ApiClient,
  DemandListParams,
  IntentListParams,
  MatchListParams,
  PageParams,
  PublicationStatus,
} from './types'

export const apiMode =
  typeof import.meta.env !== 'undefined' && import.meta.env.VITE_API_MODE === 'mock'
    ? 'mock'
    : 'http'
export const api: ApiClient =
  apiMode === 'mock'
    ? new MockApi(undefined, undefined, getAccessToken)
    : new HttpApi({ baseUrl: import.meta.env?.VITE_API_BASE_URL })
