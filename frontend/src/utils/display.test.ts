import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatMetricMatched,
  formatMetricValue,
  formatSnippetSource,
  getIntentActionState,
  intentCreationGuidance,
  intentInitiatorText,
  resolveIntentMatchId,
} from './display'

test('snippet source labels support S-10 references, repeated snippets, and legacy fields', () => {
  for (const [source_ref, label] of [
    ['achievement.abstract_original', '成果原文摘要'],
    ['achievement.title_original', '论文标题'],
    ['demand.pain_point', '需求痛点'],
    ['demand.expected_solution', '期望方案'],
    ['demand.title', '需求标题'],
    ['achievement.abstract_original', '成果原文摘要'],
  ]) {
    assert.equal(formatSnippetSource({ source_ref, field: 'legacy' }), `来源：${label}`)
  }
  assert.equal(
    formatSnippetSource({ source_ref: '', side: 'demand', field: 'title' }),
    '来源：需求标题',
  )
  assert.equal(formatSnippetSource({ field: 'demand.expected_solution' }), '来源：期望方案')
  assert.equal(
    formatSnippetSource({ source_ref: 'original_url', field: 'section' }),
    '来源：original_url',
  )
  assert.equal(formatSnippetSource({ source_ref: '', field: 'section' }), '来源：section')
})

test('metric formatting keeps missing values, zero, and unverified results distinct', () => {
  for (const value of [null, undefined, '']) {
    assert.equal(formatMetricValue(value, 'mAh/g', '尚无核查数据'), '尚无核查数据')
    assert.equal(formatMetricValue(value, '', '未指定'), '未指定')
  }
  assert.equal(formatMetricValue(0, 'mAh/g', '未指定'), '0 mAh/g')
  assert.equal(formatMetricValue('≥ 180', '', '未指定'), '≥ 180')
  assert.equal(formatMetricValue(42, undefined, '未指定'), '42')
  assert.equal(formatMetricMatched(true), '符合')
  assert.equal(formatMetricMatched(false), '不符合')
  assert.equal(formatMetricMatched(null), '尚未核实')
  assert.equal(formatMetricMatched(undefined), '尚未核实')
})

test('intent permissions follow the pair publishers, initiator, status, and disclosure flag', () => {
  const publishers = { achievementPublisherId: 'researcher', demandPublisherId: 'enterprise' }
  for (const currentUserId of ['researcher', 'enterprise', 'outsider', undefined]) {
    const isParticipant = currentUserId === 'researcher' || currentUserId === 'enterprise'
    assert.deepEqual(getIntentActionState({ ...publishers, currentUserId, intent: null }), {
      isParticipant,
      canCreate: isParticipant,
      isInitiator: false,
      canRespond: false,
      canRevealContact: false,
      statusText: '',
    })
    for (const initiator_user_id of ['researcher', 'enterprise']) {
      for (const [status, statusText] of [
        ['expressed', '已表达'],
        ['confirmed', '双方已确认'],
        ['declined', '已拒绝'],
        ['closed', '已关闭'],
      ] as const) {
        for (const contact_revealed of [false, true, undefined]) {
          const isInitiator = currentUserId === initiator_user_id
          assert.deepEqual(
            getIntentActionState({
              ...publishers,
              currentUserId,
              intent: { status, initiator_user_id, contact_revealed },
            }),
            {
              isParticipant,
              canCreate: false,
              isInitiator,
              canRespond: isParticipant && !isInitiator && status === 'expressed',
              canRevealContact:
                isParticipant && status === 'confirmed' && contact_revealed !== false,
              statusText,
            },
          )
        }
      }
    }
  }
  assert.equal(getIntentActionState({ intent: null }).isParticipant, false)
  assert.equal(
    getIntentActionState({ intent: null, currentUserId: null, demandPublisherId: null }).canCreate,
    false,
  )
  assert.equal(
    getIntentActionState({
      intent: null,
      currentUserId: 'researcher',
      achievementPublisherId: 'researcher',
      demandPublisherId: null,
    }).canCreate,
    false,
  )
})

test('intent creation guidance points to the current role’s publication only when unpublished', () => {
  for (const [role, ownObject, publishLabel, otherParty, otherObject] of [
    ['researcher', '科研成果', '前往发布成果', '企业方', '需求'],
    ['enterprise', '企业需求', '前往发布需求', '科研方', '成果'],
  ] as const) {
    assert.deepEqual(intentCreationGuidance(role, 'me', null), {
      message: `请先发布该${ownObject}后，再发起合作意向。`,
      publishLabel,
    })
    assert.deepEqual(intentCreationGuidance(role, 'me', 'someone-else'), {
      message: `该${ownObject}已由其他账号发布，当前账号无权发起合作意向。`,
    })
    assert.deepEqual(intentCreationGuidance(role, 'me', 'me'), {
      message: `等待${otherParty}发布该${otherObject}后，即可发起合作意向。`,
    })
  }
})

test('intent initiator copy names the other party and only pending intents ask for confirmation', () => {
  for (const [role, otherParty] of [
    ['researcher', '企业方'],
    ['enterprise', '科研方'],
  ] as const) {
    assert.equal(intentInitiatorText(role, true, 'expressed'), `我方发起 · 等待${otherParty}确认`)
    assert.equal(intentInitiatorText(role, false, 'expressed'), `${otherParty}发起 · 待我方确认`)
    assert.equal(intentInitiatorText(role, true, 'confirmed'), '我方发起')
    assert.equal(intentInitiatorText(role, false, 'declined'), `${otherParty}发起`)
  }
})

test('intent match links prefer the stored match ID and fall back to the pair ID', () => {
  const pair = { demand_id: 'dem_005', achievement_id: 'ach_123' }
  assert.equal(resolveIntentMatchId({ ...pair, match_id: 'current_match' }), 'current_match')
  for (const match_id of [null, '']) {
    assert.equal(resolveIntentMatchId({ ...pair, match_id }), 'match_dem_005_ach_123')
  }
})
