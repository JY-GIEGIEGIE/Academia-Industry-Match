import type { LocationQueryRaw } from 'vue-router'
import type { UserRole } from '../types'

export function recommendationsRoute(role: UserRole, context: LocationQueryRaw = {}) {
  const view = role === 'researcher' ? 'research' : 'enterprise'
  const query: LocationQueryRaw = { ...context, view }
  if (context.view !== view) delete query.object
  return { path: '/recommendations', query }
}
