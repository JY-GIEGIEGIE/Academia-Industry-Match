export type Perspective = 'enterprise' | 'research'
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
export interface Pagination {
  page: number
  page_size: number
  total: number
  total_pages: number
}
export interface Page<T> {
  items: T[]
  pagination: Pagination
}
export interface Taxonomy {
  taxonomy_version: string
  dimensions: {
    dimension: string
    label: string
    type: 'enum' | 'ordinal'
    applies_to: string[]
    values: { code: string; label: string }[]
  }[]
}
export interface Metric {
  name: string
  value: string
  unit: string
  evidence?: string
}
export interface Publication {
  publisher_user_id?: string | null
  published_at?: string | null
}
export interface AchievementSummary extends Publication {
  achievement_id: string
  title_original: string
  abstract_preview: string | null
  capability_profile_zh: string | null
  publication_year: number
  type: string
  source: string
  source_url: string
  language: string
  trl: number | null
  tech_fields: { code: string; is_primary: boolean }[]
  application_scenarios: string[]
  is_simulated: boolean
  dataset_version: string
}
export interface Achievement extends AchievementSummary {
  doi: string | null
  abstract_original: string
  venue: string | null
  keywords: string[]
  topics: string[]
  clean_status: string
  review_status: string
  trl_evidence: string | null
  key_metrics: Metric[]
  material_system: string | null
  process: string[]
  ip_status: string | null
}
export type DemandStatus = 'draft' | 'active' | 'expired' | 'closed'
export interface DemandSummary extends Publication {
  demand_id: string
  enterprise_id: string
  title: string
  pain_point: string
  required_trl: number
  status?: DemandStatus
  tech_fields: string[]
  application_scenarios: string[]
  is_simulated: boolean
  dataset_version: string
  enterprise: { display_name: string; industry: string; size: string }
}
export interface Demand extends DemandSummary {
  expected_solution: string
  technical_metrics: Metric[]
  budget_range: string | null
  timeline: string | null
  cooperation_modes: string[]
  ip_requirement: string | null
  region: string
  status: DemandStatus
  valid_until: string
  source_note: string
}
export type RiskDimension = 'technical' | 'market' | 'ip' | 'collaboration'
export type Risk = Record<RiskDimension, { score: number; description: string }> & {
  overall: { summary: string; mitigation: string[] }
}
export interface Evidence {
  tag_matches: { dimension: string; code: string }[]
  snippets: { side: 'achievement' | 'demand'; field: string; text: string; source_ref: string }[]
  metric_matches: {
    name: string
    achievement_value?: string | number | null
    required_value?: string | number | null
    unit: string
    matched?: boolean | null
  }[]
}
export interface MatchSummary {
  match_id: string
  total_score: number
  tag_score: number
  semantic_score: number
  llm_score: number | null
  risk_overall_score?: number | null
  reason: string
  achievement_summary: AchievementSummary
  demand_summary: DemandSummary
  is_stale: boolean
  created_at: string
}
export interface Match extends MatchSummary {
  risk: Risk | null
  evidence: Evidence | null
  model: string
  prompt_version: string
  dataset_version: string
  taxonomy_version: string
  embedding_model_version: string
}
export interface SeedPair extends Omit<Match, 'achievement_summary' | 'demand_summary'> {
  achievement_id: string
  demand_id: string
}
export interface Fixtures {
  achievements: Achievement[]
  demands: Demand[]
  matches: SeedPair[]
  taxonomy: Taxonomy
}

export type UserRole = 'researcher' | 'enterprise'
export interface User {
  user_id: string
  username: string
  role: UserRole
  display_name: string
}
export interface LoginData {
  token: string
  user: User
}
export interface PublishAchievementRequest {
  achievement_id: string
  updates: Record<string, never>
}
export interface PublishDemandRequest {
  demand_id: string
  updates: Record<string, never>
}
export interface PublishAchievementResult {
  achievement_id: string
  run_id: string
}
export interface PublishDemandResult {
  demand_id: string
  run_id: string
}
export interface PipelineRun {
  run_id: string
  stage: string
  status: 'running' | 'success' | 'partial' | 'failed'
  started_at: string | null
  finished_at: string | null
  error?: string | null
}
export type IntentStatus = 'expressed' | 'confirmed' | 'declined' | 'closed'
export interface CreateIntentRequest {
  achievement_id: string
  demand_id: string
}
export interface Intent extends CreateIntentRequest {
  intent_id: string
  match_id: string | null
  initiator_user_id: string
  status: IntentStatus
  contact_revealed?: boolean
  achievement_title: string
  demand_title: string
  created_at: string
  updated_at: string
}
export interface IntentStatusUpdate {
  intent_id: string
  status: IntentStatus
  contact_revealed: boolean
}
export type IntentUpdateResult = Intent | IntentStatusUpdate

interface ContactFields {
  name?: string | null
  email?: string | null
  phone?: string | null
}
export interface PartyIntentContact {
  intent_id: string
  status: 'confirmed'
  researcher_contact: ContactFields
  enterprise_contact: ContactFields
  is_simulated: true
}
export interface SimpleIntentContact {
  intent_id: string
  is_mock: true
  email: string
  phone: string
}
export type IntentContactResponse = PartyIntentContact | SimpleIntentContact
export interface IntentContact {
  intent_id: string
  is_simulated: true
  contacts: (ContactFields & { role?: UserRole })[]
}
