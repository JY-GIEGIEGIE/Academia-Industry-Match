import { normalizeIntentContact } from './contact'
import { ApiError } from './error'
import { getAccessToken } from './session'
import type {
  Achievement,
  AchievementSummary,
  ApiResponse,
  CreateIntentRequest,
  Demand,
  DemandSummary,
  Intent,
  IntentContactResponse,
  IntentUpdateResult,
  LoginData,
  Match,
  MatchSummary,
  Page,
  Perspective,
  PipelineRun,
  PublishAchievementRequest,
  PublishAchievementResult,
  PublishDemandRequest,
  PublishDemandResult,
  Taxonomy,
  User,
} from '../types'
import type {
  AchievementListParams,
  ApiClient,
  DemandListParams,
  IntentListParams,
  MatchListParams,
} from './types'

interface HttpOptions {
  baseUrl?: string
  fetch?: typeof fetch
  getToken?: () => string | null
}

function isApiResponse(value: unknown): value is ApiResponse<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    typeof value.code === 'number' &&
    'message' in value &&
    typeof value.message === 'string' &&
    'data' in value
  )
}

export class HttpApi implements ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly getToken: () => string | null
  private unauthorized?: (requestToken: string | null) => void

  constructor(options: HttpOptions = {}) {
    this.baseUrl = (options.baseUrl || '/api/v1').replace(/\/+$/, '')
    this.fetcher = options.fetch ?? ((...args) => globalThis.fetch(...args))
    this.getToken = options.getToken ?? getAccessToken
  }

  onUnauthorized(callback: (requestToken: string | null) => void) {
    this.unauthorized = callback
  }

  private async request<T>(
    path: string,
    options: { query?: object; body?: object; method?: 'POST'; anonymous?: boolean } = {},
  ) {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== null) query.set(key, String(value))
    }
    const search = query.toString()
    const headers = new Headers({ Accept: 'application/json' })
    const token = options.anonymous ? null : this.getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    if (options.body) headers.set('Content-Type', 'application/json')

    let response: Response
    try {
      response = await this.fetcher(this.baseUrl + path + (search ? `?${search}` : ''), {
        method: options.method ?? 'GET',
        headers,
        body: options.body && JSON.stringify(options.body),
      })
    } catch {
      throw new ApiError(50301, '无法连接 API 服务')
    }

    if (response.status === 401) this.unauthorized?.(token)
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      if (isApiResponse(payload) && payload.code !== 0) {
        throw new ApiError(payload.code, payload.message, response.status)
      }
      throw new ApiError(
        response.status * 100 + 1,
        `API 请求失败（HTTP ${response.status}）`,
        response.status,
      )
    }
    if (!isApiResponse(payload)) {
      throw new ApiError(50001, 'API 响应格式无效', response.status)
    }
    if (payload.code !== 0) throw new ApiError(payload.code, payload.message, response.status)
    return payload as ApiResponse<T>
  }

  login(username: string, password: string) {
    return this.request<LoginData>('/auth/login', {
      method: 'POST',
      body: { username, password },
      anonymous: true,
    })
  }

  me() {
    return this.request<User>('/auth/me')
  }

  getAchievements(query?: AchievementListParams) {
    return this.request<Page<AchievementSummary>>('/achievements', { query })
  }

  getAchievement(id: string) {
    return this.request<Achievement>(`/achievements/${encodeURIComponent(id)}`)
  }

  publishAchievement(body: PublishAchievementRequest) {
    return this.request<PublishAchievementResult>('/achievements', { method: 'POST', body })
  }

  getDemands(query?: DemandListParams) {
    return this.request<Page<DemandSummary>>('/demands', { query })
  }

  getDemand(id: string) {
    return this.request<Demand>(`/demands/${encodeURIComponent(id)}`)
  }

  publishDemand(body: PublishDemandRequest) {
    return this.request<PublishDemandResult>('/demands', { method: 'POST', body })
  }

  getTaxonomy() {
    return this.request<Taxonomy>('/taxonomy')
  }

  getPipelineRun(id: string) {
    return this.request<PipelineRun>(`/pipeline-runs/${encodeURIComponent(id)}`)
  }

  getMatches(view: Perspective, id: string, query?: MatchListParams) {
    const side = view === 'enterprise' ? 'demands' : 'achievements'
    return this.request<Page<MatchSummary>>(`/${side}/${encodeURIComponent(id)}/matches`, { query })
  }

  getMatch(id: string) {
    return this.request<Match>(`/matches/${encodeURIComponent(id)}`)
  }

  createIntent(body: CreateIntentRequest) {
    return this.request<Intent>('/intents', { method: 'POST', body })
  }

  async listIntents(query?: IntentListParams) {
    const response = await this.request<Page<Intent>>('/intents', { query })
    const status = query?.status
    if (!status) return response
    const { pagination } = response.data
    if (pagination.total === 0) return response

    // The initial S-11 list endpoint accepts the query but ignores status.
    // Filter the full authorized result set before calculating page boundaries.
    const items: Intent[] = []
    if (pagination.page === 1 && pagination.total_pages === 1) {
      items.push(...response.data.items.filter((item) => item.status === status))
    } else {
      for (let page = 1; ; page++) {
        const { data } = await this.request<Page<Intent>>('/intents', {
          query: { ...query, page, page_size: 100 },
        })
        items.push(...data.items.filter((item) => item.status === status))
        if (page >= data.pagination.total_pages) break
      }
    }
    const { page, page_size } = pagination
    return {
      ...response,
      data: {
        items: items.slice((page - 1) * page_size, page * page_size),
        pagination: {
          page,
          page_size,
          total: items.length,
          total_pages: Math.ceil(items.length / page_size),
        },
      },
    }
  }

  confirmIntent(id: string) {
    return this.request<IntentUpdateResult>(`/intents/${encodeURIComponent(id)}/confirm`, {
      method: 'POST',
    })
  }

  declineIntent(id: string) {
    return this.request<IntentUpdateResult>(`/intents/${encodeURIComponent(id)}/decline`, {
      method: 'POST',
    })
  }

  async getIntentContact(id: string) {
    const response = await this.request<IntentContactResponse>(
      `/intents/${encodeURIComponent(id)}/contact`,
    )
    return { ...response, data: normalizeIntentContact(response.data) }
  }
}
