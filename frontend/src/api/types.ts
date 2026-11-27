import type {
  Achievement,
  AchievementSummary,
  ApiResponse,
  CreateIntentRequest,
  Demand,
  DemandStatus,
  DemandSummary,
  Intent,
  IntentContact,
  IntentStatus,
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

export interface PageParams {
  page?: number
  page_size?: number
}
export type PublicationStatus = 'all' | 'unpublished' | 'mine'
interface CatalogParams extends PageParams {
  publication_status?: PublicationStatus
  tech_field?: string
  keyword?: string
}
export interface AchievementListParams extends CatalogParams {
  publication_year?: number
  trl_min?: number
  trl_max?: number
}
export interface DemandListParams extends CatalogParams {
  required_trl?: number
  region?: string
  status?: DemandStatus
  cooperation_mode?: string
}
export interface MatchListParams extends PageParams {
  min_score?: number
  is_stale?: boolean
}
export interface IntentListParams extends PageParams {
  status?: IntentStatus
  achievement_id?: string
  demand_id?: string
}

type Result<T> = Promise<ApiResponse<T>>
export interface ApiClient {
  login(username: string, password: string): Result<LoginData>
  me(): Result<User>
  getAchievements(params?: AchievementListParams): Result<Page<AchievementSummary>>
  getAchievement(id: string): Result<Achievement>
  publishAchievement(request: PublishAchievementRequest): Result<PublishAchievementResult>
  getDemands(params?: DemandListParams): Result<Page<DemandSummary>>
  getDemand(id: string): Result<Demand>
  publishDemand(request: PublishDemandRequest): Result<PublishDemandResult>
  getTaxonomy(): Result<Taxonomy>
  getPipelineRun(id: string): Result<PipelineRun>
  getMatches(view: Perspective, id: string, params?: MatchListParams): Result<Page<MatchSummary>>
  getMatch(id: string): Result<Match>
  createIntent(request: CreateIntentRequest): Result<Intent>
  listIntents(params?: IntentListParams): Result<Page<Intent>>
  confirmIntent(id: string): Result<IntentUpdateResult>
  declineIntent(id: string): Result<IntentUpdateResult>
  getIntentContact(id: string): Result<IntentContact>
}
