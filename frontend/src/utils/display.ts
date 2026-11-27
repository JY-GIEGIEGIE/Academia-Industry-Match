import { isContactRevealed } from '../api/contact'
import type { Intent, IntentStatus, UserRole } from '../types'

const snippetSources = new Map([
  ['achievement.abstract_original', '成果原文摘要'],
  ['achievement.title_original', '论文标题'],
  ['demand.pain_point', '需求痛点'],
  ['demand.expected_solution', '期望方案'],
  ['demand.title', '需求标题'],
])

export function formatSnippetSource(snippet: {
  source_ref?: string | null
  field: string
  side?: string
}): string {
  const source = snippet.source_ref || snippet.field
  const label = snippetSources.get(source) ?? snippetSources.get(`${snippet.side}.${source}`)
  return `来源：${label ?? source}`
}

export function formatMetricValue(
  value: string | number | null | undefined,
  unit: string | null | undefined,
  fallback: string,
): string {
  if (value === null || value === undefined || value === '') return fallback
  const suffix = unit?.trim()
  return suffix ? `${value} ${suffix}` : String(value)
}

export function formatMetricMatched(matched: boolean | null | undefined): string {
  if (matched === true) return '符合'
  if (matched === false) return '不符合'
  return '尚未核实'
}

export const intentStatusText: Record<IntentStatus, string> = {
  expressed: '已表达',
  confirmed: '双方已确认',
  declined: '已拒绝',
  closed: '已关闭',
}

export function intentInitiatorText(role: UserRole, isInitiator: boolean, status: IntentStatus) {
  const otherParty = role === 'researcher' ? '企业方' : '科研方'
  const initiator = isInitiator ? '我方发起' : `${otherParty}发起`
  if (status !== 'expressed') return initiator
  return `${initiator} · ${isInitiator ? `等待${otherParty}确认` : '待我方确认'}`
}

export function getIntentActionState({
  intent,
  currentUserId,
  achievementPublisherId,
  demandPublisherId,
}: {
  intent: Pick<Intent, 'initiator_user_id' | 'status' | 'contact_revealed'> | null | undefined
  currentUserId?: string | null
  achievementPublisherId?: string | null
  demandPublisherId?: string | null
}) {
  const isParticipant = Boolean(
    currentUserId &&
    (currentUserId === achievementPublisherId || currentUserId === demandPublisherId),
  )
  const isInitiator = Boolean(intent && currentUserId && intent.initiator_user_id === currentUserId)
  return {
    isParticipant,
    canCreate: !intent && isParticipant && Boolean(achievementPublisherId && demandPublisherId),
    isInitiator,
    canRespond: Boolean(intent && intent.status === 'expressed' && isParticipant && !isInitiator),
    canRevealContact: Boolean(
      intent && isParticipant && intent.status === 'confirmed' && isContactRevealed(intent),
    ),
    statusText: intent ? intentStatusText[intent.status] : '',
  }
}

export function intentCreationGuidance(
  role: UserRole,
  currentUserId: string,
  ownPublisherId?: string | null,
) {
  const ownObject = role === 'researcher' ? '科研成果' : '企业需求'
  if (!ownPublisherId) {
    return {
      message: `请先发布该${ownObject}后，再发起合作意向。`,
      publishLabel: role === 'researcher' ? '前往发布成果' : '前往发布需求',
    }
  }
  if (ownPublisherId !== currentUserId) {
    return { message: `该${ownObject}已由其他账号发布，当前账号无权发起合作意向。` }
  }
  return {
    message:
      role === 'researcher'
        ? '等待企业方发布该需求后，即可发起合作意向。'
        : '等待科研方发布该成果后，即可发起合作意向。',
  }
}

export function resolveIntentMatchId(
  intent: Pick<Intent, 'match_id' | 'demand_id' | 'achievement_id'>,
): string {
  return intent.match_id || `match_${intent.demand_id}_${intent.achievement_id}`
}
