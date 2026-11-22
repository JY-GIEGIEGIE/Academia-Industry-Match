import test from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError, fixtures, MockApi } from './api'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
const fastApi = new MockApi(fixtures, 0)
test('20 unique pair fixtures preserve privacy, versions, provenance and excerpt limits', () => {
  assert.equal(fixtures.matches.length, 20)
  assert.equal(new Set(fixtures.matches.map((m) => m.achievement_id + '|' + m.demand_id)).size, 20)
  for (const a of fixtures.achievements) {
    assert.equal(a.is_simulated, false)
    assert.equal(a.trl, null)
    assert.equal(a.ip_status, 'unknown')
    assert.ok(a.abstract_original.length <= 600)
    assert.ok((a.abstract_preview?.length || 0) <= 300)
    assert.equal(a.dataset_version, 'v0.1')
    for (const forbidden of ['authors', 'institutions', 'legal_name', 'raw_payload_path'])
      assert.ok(!(forbidden in a))
  }
  for (const d of fixtures.demands) {
    assert.equal(d.is_simulated, true)
    assert.equal(d.dataset_version, 'v0.1')
    assert.ok(!('legal_name' in d.enterprise))
    assert.ok(!('contacts' in d.enterprise))
  }
  for (const m of fixtures.matches) {
    assert.equal(m.dataset_version, 'v0.1')
    assert.equal(m.taxonomy_version, 'v0.1')
    assert.equal(m.embedding_model_version, 'mock-only-no-embedding')
    assert.match(m.model, /mock-only/)
    assert.ok(m.total_score >= 0 && m.total_score <= 100)
    if (m.risk)
      for (const key of ['technical', 'market', 'ip', 'collaboration'] as const)
        assert.ok(m.risk[key].score >= 1 && m.risk[key].score <= 5)
    for (const metric of m.evidence?.metric_matches || []) {
      assert.equal(metric.achievement_value, undefined)
      assert.equal(metric.matched, undefined)
    }
  }
  const data = readFileSync(new URL('./fixtures.json', import.meta.url))
  const manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))
  assert.equal(createHash('sha256').update(data).digest('hex'), manifest.hash)
})
test('taxonomy uses all 11 API dimensions, complete enum sets and string codes', async () => {
  const response = await fastApi.getTaxonomy()
  const dims = response.data.dimensions.map((d) => d.dimension)
  assert.deepEqual(
    new Set(dims),
    new Set([
      'tech_field',
      'application_scenario',
      'cooperation_mode',
      'ip_status',
      'region',
      'industry',
      'enterprise_size',
      'status',
      'language',
      'type',
      'trl',
    ]),
  )
  assert.equal(response.data.dimensions.find((d) => d.dimension === 'tech_field')?.values.length, 8)
  assert.equal(response.data.dimensions.find((d) => d.dimension === 'trl')?.values.length, 9)
  assert.ok(
    response.data.dimensions.every((d) => d.values.every((v) => typeof v.code === 'string')),
  )
})
test('achievement and demand lists use the contract pagination shape', async () => {
  const achievements = await fastApi.getAchievements({ page: 1, page_size: 2 })
  assert.equal(achievements.data.items.length, 2)
  assert.deepEqual(achievements.data.pagination, {
    page: 1,
    page_size: 2,
    total: 4,
    total_pages: 2,
  })
  const demands = await fastApi.getDemands({ page: 2, page_size: 2 })
  assert.equal(demands.data.items.length, 2)
  assert.deepEqual(demands.data.pagination, {
    page: 2,
    page_size: 2,
    total: 5,
    total_pages: 3,
  })
  const defaultAchievements = await fastApi.getAchievements()
  assert.equal(defaultAchievements.data.pagination.page_size, 20)
  assert.equal(defaultAchievements.data.items.length, 4)
  assert.throws(
    () => fastApi.getAchievements({ page: 0 }),
    (e) => e instanceof ApiError && e.code === 40001,
  )
  assert.throws(
    () => fastApi.getDemands({ page_size: 101 }),
    (e) => e instanceof ApiError && e.code === 40001,
  )
})
test('both perspectives resolve the same pair and summary does not leak detail fields', async () => {
  const pair = fixtures.matches[0]
  const enterprise = await fastApi.getMatches('enterprise', pair.demand_id, { page_size: 20 })
  const research = await fastApi.getMatches('research', pair.achievement_id, { page_size: 20 })
  const e = enterprise.data.items.find((m) => m.match_id === pair.match_id),
    r = research.data.items.find((m) => m.match_id === pair.match_id)
  assert.deepEqual(e, r)
  assert.equal(enterprise.code, 0)
  assert.ok(
    e && !('risk' in e) && !('evidence' in e) && !('abstract_original' in e.achievement_summary),
  )
  const detail = await fastApi.getMatch(pair.match_id)
  assert.deepEqual(detail.data.achievement_summary, e.achievement_summary)
  assert.equal(detail.data.demand_summary.demand_id, pair.demand_id)
})
test('pagination and minimum-score filter report correct counts without duplicate rows', async () => {
  const id = fixtures.demands[0].demand_id
  const first = await fastApi.getMatches('enterprise', id, { page: 1, page_size: 3 })
  const second = await fastApi.getMatches('enterprise', id, { page: 2, page_size: 3 })
  assert.equal(first.data.pagination.total, 4)
  assert.equal(first.data.pagination.total_pages, 2)
  assert.equal(first.data.items.length, 3)
  assert.equal(second.data.items.length, 1)
  assert.equal(new Set([...first.data.items, ...second.data.items].map((m) => m.match_id)).size, 4)
  const filtered = await fastApi.getMatches('enterprise', id, { min_score: 80, page_size: 20 })
  assert.equal(filtered.data.pagination.total, 2)
  assert.ok(filtered.data.items.every((m) => m.total_score >= 80))
  const empty = await fastApi.getMatches('enterprise', id, { min_score: 100 })
  assert.equal(empty.data.pagination.total, 0)
  assert.equal(empty.data.pagination.total_pages, 0)
  const defaultPage = await fastApi.getMatches('enterprise', id)
  assert.equal(defaultPage.data.pagination.page_size, 20)
})
test('stale and unfinished risks stay null instead of becoming low risk', async () => {
  const old = fixtures.matches.find((m) => m.is_stale)!
  const response = await fastApi.getMatches('enterprise', old.demand_id, {
    is_stale: true,
    page_size: 20,
  })
  assert.ok(response.data.items.length > 0)
  assert.ok(response.data.items.every((m) => m.is_stale && m.risk_overall_score === null))
  const detail = await fastApi.getMatch(old.match_id)
  assert.equal(detail.data.risk, null)
  assert.equal(detail.data.evidence, null)
  const pending = fixtures.matches.find((m) => !m.is_stale && m.risk === null)!
  assert.equal((await fastApi.getMatch(pending.match_id)).data.risk, null)
})
test('invalid parameters and missing objects return contract error codes', async () => {
  for (const params of [
    { page: 0 },
    { page: 1.5 },
    { page_size: 101 },
    { min_score: NaN },
    { min_score: 101 },
  ]) {
    assert.throws(
      () => fastApi.getMatches('enterprise', fixtures.demands[0].demand_id, params),
      (e) => e instanceof ApiError && e.code === 40001,
    )
  }
  assert.throws(
    () => fastApi.getMatch('missing'),
    (e) => e instanceof ApiError && e.code === 40401,
  )
  assert.throws(
    () => fastApi.getMatches('enterprise', 'missing'),
    (e) => e instanceof ApiError && e.code === 40401,
  )
})
test('responses are isolated copies, so frontend edits cannot alter source fixtures', async () => {
  const one = await api.getMatch(fixtures.matches[0].match_id)
  one.data.demand_summary.enterprise.display_name = 'changed'
  const two = await fastApi.getMatch(fixtures.matches[0].match_id)
  assert.notEqual(two.data.demand_summary.enterprise.display_name, 'changed')
})
