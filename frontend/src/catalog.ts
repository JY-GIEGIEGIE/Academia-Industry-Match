import { reactive } from 'vue'
import { api } from './mock/api'
import type { AchievementSummary, DemandSummary, Taxonomy } from './types'
export const catalog = reactive<{
  achievements: AchievementSummary[]
  demands: DemandSummary[]
  taxonomy: Taxonomy | null
}>({ achievements: [], demands: [], taxonomy: null })
export const catalogReady = Promise.all([
  api.getAchievements(),
  api.getDemands(),
  api.getTaxonomy(),
]).then(([a, d, t]) => {
  catalog.achievements = a.data
  catalog.demands = d.data
  catalog.taxonomy = t.data
})
export function label(dimension: string, code: string | number | null | undefined): string {
  if (code === null || code === undefined) return '待评估'
  return (
    catalog.taxonomy?.dimensions
      .find((d) => d.dimension === dimension)
      ?.values.find((v) => String(v.code) === String(code))?.label ?? '待确认'
  )
}
export function labels(dimension: string, codes: string[]): string {
  return codes.length ? codes.map((code) => label(dimension, code)).join('、') : '待确认'
}
export function safeSource(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url : undefined
  } catch {
    return undefined
  }
}
