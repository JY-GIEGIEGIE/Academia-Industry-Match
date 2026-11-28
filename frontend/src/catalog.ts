import { reactive } from 'vue'
import { api } from './api'
import type { AchievementListParams, DemandListParams, PageParams } from './api'
import type {
  AchievementSummary,
  ApiResponse,
  DemandSummary,
  Page,
  Perspective,
  Taxonomy,
} from './types'
export const catalog = reactive<{
  achievements: AchievementSummary[]
  demands: DemandSummary[]
  taxonomy: Taxonomy | null
}>({ achievements: [], demands: [], taxonomy: null })

let taxonomyRequest: Promise<Taxonomy> | undefined
export async function loadTaxonomy(): Promise<Taxonomy> {
  if (catalog.taxonomy) return catalog.taxonomy
  taxonomyRequest ??= api
    .getTaxonomy()
    .then(({ data }) => {
      catalog.taxonomy = data
      return data
    })
    .finally(() => {
      taxonomyRequest = undefined
    })
  return taxonomyRequest
}

export function loadAchievements(params?: AchievementListParams) {
  return api.getAchievements(params)
}

export function loadDemands(params?: DemandListParams) {
  return api.getDemands(params)
}

export function loadObject(view: Perspective, id: string) {
  return view === 'enterprise' ? api.getDemand(id) : api.getAchievement(id)
}

export function loadUserObjects(view: Perspective, params?: PageParams) {
  const filters = { ...params, publication_status: 'mine' as const }
  return view === 'enterprise' ? loadDemands(filters) : loadAchievements(filters)
}

async function loadAll<T>(loadPage: (params: PageParams) => Promise<ApiResponse<Page<T>>>) {
  const items: T[] = []
  for (let page = 1; ; page++) {
    const { data } = await loadPage({ page, page_size: 100 })
    items.push(...data.items)
    if (page >= data.pagination.total_pages) return items
  }
}

const objectRequests: Partial<Record<Perspective, Promise<void>>> = {}
export function loadCatalogObjects(view: Perspective, { force = false } = {}): Promise<void> {
  const cached = objectRequests[view]
  if (cached && !force) return cached

  const load =
    view === 'enterprise'
      ? loadAll(loadDemands).then((demands) => {
          if (objectRequests[view] === request) catalog.demands = demands
          else return objectRequests[view]
        })
      : loadAll(loadAchievements).then((achievements) => {
          if (objectRequests[view] === request) catalog.achievements = achievements
          else return objectRequests[view]
        })
  const request: Promise<void> = load.catch((error: unknown) => {
    if (objectRequests[view] === request) delete objectRequests[view]
    throw error
  })
  objectRequests[view] = request
  return request
}
export function label(dimension: string, code: string | number | null | undefined): string {
  if (code === null || code === undefined) return '待评估'
  return (
    catalog.taxonomy?.dimensions
      .find((d) => d.dimension === dimension)
      ?.values.find((v) => String(v.code) === String(code))?.label ?? '待确认'
  )
}
export function labels(dimension: string, codes: string[]): string {
  if (codes.length) return codes.map((code) => label(dimension, code)).join('、')
  return dimension === 'application_scenario' ? '待确认/未知' : '待确认'
}
export function safeSource(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url : undefined
  } catch {
    return undefined
  }
}
