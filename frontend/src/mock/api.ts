import fixturesJson from './fixtures.json'
import type {
  Achievement,
  AchievementSummary,
  ApiResponse,
  Demand,
  DemandSummary,
  Fixtures,
  Match,
  MatchSummary,
  Page,
  Perspective,
  SeedPair,
} from '../types'
export const fixtures = fixturesJson as Fixtures
export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
  ) {
    super(message)
  }
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
  }
}
export class MockApi {
  constructor(
    private data: Fixtures = fixtures,
    private delay = 90,
  ) {}
  private async respond<T>(data: T): Promise<ApiResponse<T>> {
    if (this.delay) await new Promise((resolve) => setTimeout(resolve, this.delay))
    return { code: 0, message: 'success', data: structuredClone(data) }
  }
  private paginate<T>(items: T[], params: { page?: number; page_size?: number } = {}): Page<T> {
    const { page = 1, page_size = 20 } = params
    if (
      !Number.isInteger(page) ||
      page < 1 ||
      !Number.isInteger(page_size) ||
      page_size < 1 ||
      page_size > 100
    )
      throw new ApiError(40001, '筛选或页码参数无效')
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
  private findAchievement(id: string) {
    const a = this.data.achievements.find((item) => item.achievement_id === id)
    if (!a) throw new ApiError(40401, '找不到这条科研成果')
    return a
  }
  private findDemand(id: string) {
    const d = this.data.demands.find((item) => item.demand_id === id)
    if (!d) throw new ApiError(40401, '找不到这条企业需求')
    return d
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
  getTaxonomy() {
    return this.respond(this.data.taxonomy)
  }
  getAchievements(
    params: { page?: number; page_size?: number } = {},
  ): Promise<ApiResponse<Page<AchievementSummary>>> {
    return this.respond(this.paginate(this.data.achievements.map(achievementSummary), params))
  }
  getDemands(
    params: { page?: number; page_size?: number } = {},
  ): Promise<ApiResponse<Page<DemandSummary>>> {
    return this.respond(this.paginate(this.data.demands.map(demandSummary), params))
  }
  getAchievement(id: string) {
    return this.respond(this.findAchievement(id))
  }
  getDemand(id: string) {
    return this.respond(this.findDemand(id))
  }
  getMatches(
    view: Perspective,
    id: string,
    params: { page?: number; page_size?: number; min_score?: number; is_stale?: boolean } = {},
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
      throw new ApiError(40001, '筛选或页码参数无效')
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
    if (!m) throw new ApiError(40401, '这条匹配记录不存在')
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
}
export const api = new MockApi()
