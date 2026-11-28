import fixturesJson from './fixtures.json'
import { normalizeIntentContact } from '../api/contact'
import { ApiError } from '../api/error'
import { browserSessionStorage } from '../api/session'
import type {
  AchievementListParams,
  ApiClient,
  DemandListParams,
  IntentListParams,
  MatchListParams,
  PageParams,
  PublicationStatus,
} from '../api/types'
import type {
  Achievement,
  AchievementSummary,
  ApiResponse,
  CreateIntentRequest,
  Demand,
  DemandSummary,
  Fixtures,
  Intent,
  Match,
  MatchSummary,
  Page,
  Perspective,
  PipelineRun,
  PublishAchievementRequest,
  PublishDemandRequest,
  SeedPair,
  User,
  UserRole,
} from '../types'
export const fixtures = fixturesJson as Fixtures
export { ApiError } from '../api/error'

const SESSION_KEY = 'aim_mock_session_v1'
const DEMO_USERS: readonly User[] = [
  {
    user_id: 'user_research_demo',
    username: 'research_demo',
    role: 'researcher',
    display_name: '科研演示用户',
  },
  {
    user_id: 'user_enterprise_demo',
    username: 'enterprise_demo',
    role: 'enterprise',
    display_name: '企业演示用户',
  },
]

interface MockPublication {
  publisher_user_id: string
  published_at: string
}

interface MockRun {
  run: PipelineRun
  polled: boolean
}

interface MockSnapshot {
  publications: [string, MockPublication][]
  runs: [string, MockRun][]
  intents: [string, Intent][]
}

function demoToken(user: User) {
  return `aim_mock_${user.username}`
}

function readSnapshot(storage?: Storage): Partial<MockSnapshot> {
  try {
    const raw = storage?.getItem(SESSION_KEY)
    if (raw) {
      const snapshot = JSON.parse(raw) as MockSnapshot
      return {
        publications: Array.isArray(snapshot?.publications) ? snapshot.publications : [],
        runs: Array.isArray(snapshot?.runs) ? snapshot.runs : [],
        intents: Array.isArray(snapshot?.intents) ? snapshot.intents : [],
      }
    }
  } catch {
    // Start with a new mock session when storage cannot be read.
  }
  return {}
}
export function achievementSummary(a: Achievement): AchievementSummary {
  const {
    achievement_id,
    title_original,
    abstract_preview,
    capability_profile_zh,
    publication_year,
    type,
    source,
    source_url,
    language,
    trl,
    tech_fields,
    application_scenarios,
    is_simulated,
    dataset_version,
    publisher_user_id,
    published_at,
  } = a
  return {
    achievement_id,
    title_original,
    abstract_preview,
    capability_profile_zh,
    publication_year,
    type,
    source,
    source_url,
    language,
    trl,
    tech_fields,
    application_scenarios,
    is_simulated,
    dataset_version,
    publisher_user_id,
    published_at,
  }
}
export function demandSummary(d: Demand): DemandSummary {
  const {
    demand_id,
    enterprise_id,
    title,
    pain_point,
    required_trl,
    tech_fields,
    application_scenarios,
    is_simulated,
    dataset_version,
    enterprise,
    status,
    publisher_user_id,
    published_at,
  } = d
  return {
    demand_id,
    enterprise_id,
    title,
    pain_point,
    required_trl,
    tech_fields,
    application_scenarios,
    is_simulated,
    dataset_version,
    enterprise,
    status,
    publisher_user_id,
    published_at,
  }
}
export class MockApi implements ApiClient {
  private readonly storage: Storage | undefined
  private readonly publications: Map<string, MockPublication>
  private readonly runs: Map<string, MockRun>
  private readonly intents: Map<string, Intent>
  private localToken: string | null = null

  constructor(
    private data: Fixtures = fixtures,
    private delay = 90,
    private readToken?: () => string | null,
  ) {
    this.storage = data === fixtures ? browserSessionStorage() : undefined
    const snapshot = readSnapshot(this.storage)
    this.publications = new Map(snapshot.publications)
    this.runs = new Map(snapshot.runs)
    this.intents = new Map(snapshot.intents)
  }

  private saveSession() {
    if (!this.storage) return
    const snapshot: MockSnapshot = {
      publications: [...this.publications],
      runs: [...this.runs],
      intents: [...this.intents],
    }
    try {
      this.storage.setItem(SESSION_KEY, JSON.stringify(snapshot))
    } catch {
      // Keep mock changes in memory when browser storage is unavailable.
    }
  }

  private async respond<T>(data: T): Promise<ApiResponse<T>> {
    const result = structuredClone(data)
    if (this.delay) await new Promise((resolve) => setTimeout(resolve, this.delay))
    return { code: 0, message: 'success', data: result }
  }
  private paginate<T>(items: T[], params: PageParams = {}): Page<T> {
    const { page = 1, page_size = 20 } = params
    if (
      !Number.isInteger(page) ||
      page < 1 ||
      !Number.isInteger(page_size) ||
      page_size < 1 ||
      page_size > 100
    )
      throw new ApiError(40001, '筛选或页码参数无效', 400)
    return {
      items: items.slice((page - 1) * page_size, page * page_size),
      pagination: {
        page,
        page_size,
        total: items.length,
        total_pages: Math.ceil(items.length / page_size),
      },
    }
  }
  private withAchievementPublication(item: Achievement): Achievement {
    const publication = this.publications.get(item.achievement_id)
    return publication ? { ...item, ...publication, clean_status: 'published' } : item
  }
  private withDemandPublication(item: Demand): Demand {
    const publication = this.publications.get(item.demand_id)
    return publication ? { ...item, ...publication, status: 'active' } : item
  }
  private findAchievement(id: string) {
    const a = this.data.achievements.find((item) => item.achievement_id === id)
    if (!a) throw new ApiError(40401, '找不到这条科研成果', 404)
    return this.withAchievementPublication(a)
  }
  private findDemand(id: string) {
    const d = this.data.demands.find((item) => item.demand_id === id)
    if (!d) throw new ApiError(40401, '找不到这条企业需求', 404)
    return this.withDemandPublication(d)
  }
  private summarize(m: SeedPair): MatchSummary {
    return {
      match_id: m.match_id,
      total_score: m.total_score,
      tag_score: m.tag_score,
      semantic_score: m.semantic_score,
      llm_score: m.llm_score,
      risk_overall_score: m.is_stale ? null : m.risk_overall_score,
      reason: m.reason,
      is_stale: m.is_stale,
      created_at: m.created_at,
      achievement_summary: achievementSummary(this.findAchievement(m.achievement_id)),
      demand_summary: demandSummary(this.findDemand(m.demand_id)),
    }
  }

  private currentUser(role?: UserRole) {
    const token = this.readToken ? this.readToken() : this.localToken
    const user = DEMO_USERS.find((candidate) => demoToken(candidate) === token)
    if (!user) throw new ApiError(40101, '请先登录', 401)
    if (role && role !== user.role) throw new ApiError(40301, '当前角色没有操作权限', 403)
    return user
  }

  async login(username: string, password: string) {
    const user = DEMO_USERS.find((candidate) => candidate.username === username)
    if (!user || !password) throw new ApiError(40101, '用户名或密码无效', 401)
    const token = demoToken(user)
    this.localToken = token
    return this.respond({ token, user })
  }

  async me() {
    return this.respond(this.currentUser())
  }

  getTaxonomy() {
    return this.respond(this.data.taxonomy)
  }

  private publicationFilter(status: PublicationStatus = 'all') {
    if (status === 'all') return () => true
    if (status === 'unpublished')
      return (item: Achievement | Demand) => item.publisher_user_id == null
    const user = this.currentUser()
    return (item: Achievement | Demand) => item.publisher_user_id === user.user_id
  }

  getAchievements(
    params: AchievementListParams = {},
  ): Promise<ApiResponse<Page<AchievementSummary>>> {
    const { tech_field, publication_year, trl_min, trl_max, keyword } = params
    const filterPublication = this.publicationFilter(params.publication_status)
    for (const bound of [trl_min, trl_max]) {
      if (bound !== undefined && (!Number.isInteger(bound) || bound < 1 || bound > 9)) {
        throw new ApiError(42201, '成熟度范围必须为 1–9', 422)
      }
    }
    if (trl_min !== undefined && trl_max !== undefined && trl_min > trl_max) {
      throw new ApiError(40001, '最低成熟度不能大于最高成熟度', 400)
    }
    const search = keyword?.toLowerCase()
    const rows = this.data.achievements
      .map((item) => this.withAchievementPublication(item))
      .filter(filterPublication)
      .filter(
        (item) =>
          (tech_field === undefined ||
            item.tech_fields.some((field) => field.code === tech_field)) &&
          (publication_year === undefined || item.publication_year === publication_year) &&
          (trl_min === undefined || (item.trl !== null && item.trl >= trl_min)) &&
          (trl_max === undefined || (item.trl !== null && item.trl <= trl_max)) &&
          (!search ||
            [item.title_original, item.abstract_original, item.capability_profile_zh].some((text) =>
              text?.toLowerCase().includes(search),
            )),
      )
    return this.respond(this.paginate(rows.map(achievementSummary), params))
  }
  getDemands(params: DemandListParams = {}): Promise<ApiResponse<Page<DemandSummary>>> {
    const { tech_field, required_trl, region, status, cooperation_mode, keyword } = params
    const filterPublication = this.publicationFilter(params.publication_status)
    if (
      required_trl !== undefined &&
      (!Number.isInteger(required_trl) || required_trl < 1 || required_trl > 9)
    ) {
      throw new ApiError(42201, '成熟度范围必须为 1–9', 422)
    }
    const search = keyword?.toLowerCase()
    const rows = this.data.demands
      .map((item) => this.withDemandPublication(item))
      .filter(filterPublication)
      .filter(
        (item) =>
          (tech_field === undefined || item.tech_fields.includes(tech_field)) &&
          (required_trl === undefined || item.required_trl === required_trl) &&
          (region === undefined || item.region === region) &&
          (status === undefined || item.status === status) &&
          (cooperation_mode === undefined || item.cooperation_modes.includes(cooperation_mode)) &&
          (!search ||
            [item.title, item.pain_point, item.expected_solution].some((text) =>
              text.toLowerCase().includes(search),
            )),
      )
    return this.respond(this.paginate(rows.map(demandSummary), params))
  }
  getAchievement(id: string) {
    return this.respond(this.findAchievement(id))
  }
  getDemand(id: string) {
    return this.respond(this.findDemand(id))
  }

  private publish(record: Achievement | Demand, id: string, user: User) {
    if (record.publisher_user_id != null) throw new ApiError(40901, '该记录已发布', 409)
    const published_at = new Date().toISOString()
    const run_id = `run_mock_${crypto.randomUUID()}`
    this.publications.set(id, { publisher_user_id: user.user_id, published_at })
    this.runs.set(run_id, {
      run: {
        run_id,
        stage: 'match',
        status: 'running',
        started_at: published_at,
        finished_at: null,
      },
      polled: false,
    })
    this.saveSession()
    return run_id
  }

  async publishAchievement({ achievement_id, updates }: PublishAchievementRequest) {
    const user = this.currentUser('researcher')
    if (!achievement_id || Object.keys(updates).length)
      throw new ApiError(42201, '发布需要成果 ID 和空的 updates', 422)
    const run_id = this.publish(this.findAchievement(achievement_id), achievement_id, user)
    return this.respond({ achievement_id, run_id })
  }

  async publishDemand({ demand_id, updates }: PublishDemandRequest) {
    const user = this.currentUser('enterprise')
    if (!demand_id || Object.keys(updates).length)
      throw new ApiError(42201, '发布需要需求 ID 和空的 updates', 422)
    const run_id = this.publish(this.findDemand(demand_id), demand_id, user)
    return this.respond({ demand_id, run_id })
  }

  async getPipelineRun(id: string) {
    this.currentUser()
    const task = this.runs.get(id)
    if (!task) throw new ApiError(40401, '找不到这条匹配任务', 404)
    if (task.polled && task.run.status === 'running') {
      task.run.status = 'success'
      task.run.finished_at = new Date().toISOString()
    }
    task.polled = true
    this.saveSession()
    return this.respond(task.run)
  }

  getMatches(
    view: Perspective,
    id: string,
    params: MatchListParams = {},
  ): Promise<ApiResponse<Page<MatchSummary>>> {
    const { page = 1, page_size = 20, min_score = 0, is_stale = false } = params
    if (
      !Number.isInteger(page) ||
      page < 1 ||
      !Number.isInteger(page_size) ||
      page_size < 1 ||
      page_size > 100 ||
      !Number.isFinite(min_score) ||
      min_score < 0 ||
      min_score > 100
    )
      throw new ApiError(40001, '筛选或页码参数无效', 400)
    if (view === 'enterprise') this.findDemand(id)
    else this.findAchievement(id)
    const rows = this.data.matches
      .filter(
        (m) =>
          (view === 'enterprise' ? m.demand_id : m.achievement_id) === id &&
          m.total_score >= min_score &&
          m.is_stale === is_stale,
      )
      .sort((a, b) => b.total_score - a.total_score || a.match_id.localeCompare(b.match_id))
    return this.respond({
      items: rows.slice((page - 1) * page_size, page * page_size).map((m) => this.summarize(m)),
      pagination: {
        page,
        page_size,
        total: rows.length,
        total_pages: Math.ceil(rows.length / page_size),
      },
    })
  }
  getMatch(id: string): Promise<ApiResponse<Match>> {
    const m = this.data.matches.find((item) => item.match_id === id)
    if (!m) throw new ApiError(40401, '这条匹配记录不存在', 404)
    return this.respond({
      ...this.summarize(m),
      risk: m.is_stale ? null : m.risk,
      evidence: m.is_stale ? null : m.evidence,
      model: m.model,
      prompt_version: m.prompt_version,
      dataset_version: m.dataset_version,
      taxonomy_version: m.taxonomy_version,
      embedding_model_version: m.embedding_model_version,
    })
  }

  private isParticipant(user: User, achievement: Achievement, demand: Demand) {
    const record = user.role === 'researcher' ? achievement : demand
    return record.publisher_user_id === user.user_id
  }

  async createIntent({ achievement_id, demand_id }: CreateIntentRequest) {
    const user = this.currentUser()
    if (!achievement_id || !demand_id) throw new ApiError(42201, '缺少配对所需的 ID', 422)
    const achievement = this.findAchievement(achievement_id)
    const demand = this.findDemand(demand_id)
    if (!this.isParticipant(user, achievement, demand)) {
      throw new ApiError(40301, '只有相关发布者可以发起合作意向', 403)
    }
    if (!achievement.publisher_user_id || !demand.publisher_user_id) {
      throw new ApiError(40901, '双方均须先发布，才能发起合作意向', 409)
    }
    const samePair = (item: CreateIntentRequest) =>
      item.achievement_id === achievement_id && item.demand_id === demand_id
    if ([...this.intents.values()].some(samePair)) {
      throw new ApiError(40901, '该配对已有合作意向', 409)
    }
    const match = this.data.matches
      .filter((item) => samePair(item) && !item.is_stale)
      .sort(
        (a, b) => b.created_at.localeCompare(a.created_at) || b.match_id.localeCompare(a.match_id),
      )[0]
    const now = new Date().toISOString()
    const intent: Intent = {
      intent_id: `intent_mock_${crypto.randomUUID()}`,
      achievement_id,
      demand_id,
      match_id: match?.match_id ?? null,
      initiator_user_id: user.user_id,
      status: 'expressed',
      contact_revealed: false,
      achievement_title: achievement.title_original,
      demand_title: demand.title,
      created_at: now,
      updated_at: now,
    }
    this.intents.set(intent.intent_id, intent)
    this.saveSession()
    return this.respond(intent)
  }

  private participatesInIntent(user: User, intent: Intent) {
    return this.isParticipant(
      user,
      this.findAchievement(intent.achievement_id),
      this.findDemand(intent.demand_id),
    )
  }

  async listIntents(params: IntentListParams = {}) {
    const user = this.currentUser()
    const { status, achievement_id, demand_id } = params
    const rows = [...this.intents.values()]
      .filter((intent) => this.participatesInIntent(user, intent))
      .filter(
        (intent) =>
          (status === undefined || intent.status === status) &&
          (achievement_id === undefined || intent.achievement_id === achievement_id) &&
          (demand_id === undefined || intent.demand_id === demand_id),
      )
      .sort(
        (a, b) =>
          b.created_at.localeCompare(a.created_at) || b.intent_id.localeCompare(a.intent_id),
      )
    return this.respond(this.paginate(rows, params))
  }

  private findParticipantIntent(id: string, user: User) {
    const intent = this.intents.get(id)
    if (!intent) throw new ApiError(40401, '找不到这条合作意向', 404)
    if (!this.participatesInIntent(user, intent))
      throw new ApiError(40301, '只有合作双方可以访问此意向', 403)
    return intent
  }

  private async updateIntentStatus(id: string, status: 'confirmed' | 'declined') {
    const user = this.currentUser()
    const intent = this.findParticipantIntent(id, user)
    if (intent.initiator_user_id === user.user_id)
      throw new ApiError(40301, '发起方不能自行确认或拒绝', 403)
    if (intent.status !== 'expressed') throw new ApiError(40901, '该合作意向已处理', 409)
    intent.status = status
    intent.contact_revealed = status === 'confirmed'
    intent.updated_at = new Date().toISOString()
    this.saveSession()
    return this.respond(intent)
  }

  confirmIntent(id: string) {
    return this.updateIntentStatus(id, 'confirmed')
  }

  declineIntent(id: string) {
    return this.updateIntentStatus(id, 'declined')
  }

  async getIntentContact(id: string) {
    const intent = this.findParticipantIntent(id, this.currentUser())
    if (intent.status !== 'confirmed' || !intent.contact_revealed) {
      throw new ApiError(40301, '确认合作意向后才可查看联系方式', 403)
    }
    return this.respond(
      normalizeIntentContact({
        intent_id: id,
        status: 'confirmed',
        is_simulated: true,
        researcher_contact: { name: '科研方演示联系人', email: 'researcher@example.invalid' },
        enterprise_contact: { name: '企业方演示联系人', email: 'enterprise@example.invalid' },
      }),
    )
  }
}
export const api = /* @__PURE__ */ new MockApi()
