import assert from 'node:assert/strict'
import test from 'node:test'
import { fixtures, MockApi } from '../mock/api'
import type { Intent, IntentContactResponse, LoginData } from '../types'
import { apiMode, ApiError, isContactRevealed, normalizeIntentContact } from './index'
import { HttpApi } from './http'
import { getAccessToken, setAccessToken } from './session'

function success<T>(data: T) {
  return Response.json({ code: 0, message: 'success', data })
}

function failure(status: number, message: string) {
  return Response.json({ code: status * 100 + 1, message, data: null }, { status })
}

function apiError(status: number, message?: string) {
  return (error: unknown) =>
    error instanceof ApiError &&
    error.code === status * 100 + 1 &&
    error.httpStatus === status &&
    (message === undefined || error.message === message)
}

test('HTTP is the default and authenticates requests with the current token', async () => {
  assert.equal(apiMode, 'http')
  const requests: { url: string; init?: RequestInit }[] = []
  let token = 'first-token'
  const api = new HttpApi({
    getToken: () => token,
    fetch: async (input, init) => {
      requests.push({ url: String(input), init })
      return success({})
    },
  })

  await api.me()
  token = 'second-token'
  await api.publishAchievement({ achievement_id: 'sample-id', updates: {} })
  await api.login('sample-user', 'test-only')
  assert.deepEqual(
    requests.map(({ url }) => url),
    ['/api/v1/auth/me', '/api/v1/achievements', '/api/v1/auth/login'],
  )
  assert.deepEqual(
    requests.map(({ init }) => new Headers(init?.headers).get('Authorization')),
    ['Bearer first-token', 'Bearer second-token', null],
  )
  assert.equal(requests[1].init?.method, 'POST')
  assert.equal(new Headers(requests[1].init?.headers).get('Content-Type'), 'application/json')
  assert.deepEqual(JSON.parse(String(requests[1].init?.body)), {
    achievement_id: 'sample-id',
    updates: {},
  })
  assert.deepEqual(JSON.parse(String(requests[2].init?.body)), {
    username: 'sample-user',
    password: 'test-only',
  })
})

test('HTTP keeps business errors and transport status, including early pipeline 404s', async () => {
  const responses = [
    failure(401, 'Session expired'),
    failure(409, 'Record already published'),
    failure(403, 'Forbidden'),
    failure(422, 'Validation error'),
    failure(404, 'Pipeline run not found'),
    new Response('<html>Bad Gateway</html>', { status: 502 }),
    new Response('<html>Proxy fallback</html>'),
    Response.json({ unexpected: true }),
    Response.json({ code: 40901, message: 'Conflict', data: null }),
  ]
  const unauthorized: (string | null)[] = []
  const api = new HttpApi({
    getToken: () => 'expired-token',
    fetch: async () => {
      const next = responses.shift()
      if (!next) throw new TypeError('Network failure')
      return next
    },
  })
  api.onUnauthorized((token) => unauthorized.push(token))
  await assert.rejects(api.me(), apiError(401, 'Session expired'))
  await assert.rejects(
    api.publishDemand({ demand_id: 'd-1', updates: {} }),
    apiError(409, 'Record already published'),
  )
  await assert.rejects(api.confirmIntent('intent-1'), apiError(403, 'Forbidden'))
  await assert.rejects(api.getAchievements({ page: 0 }), apiError(422, 'Validation error'))
  await assert.rejects(api.getPipelineRun('run-1'), apiError(404, 'Pipeline run not found'))
  await assert.rejects(api.getMatch('m-1'), apiError(502))
  await assert.rejects(api.getTaxonomy(), { code: 50001, httpStatus: 200 })
  await assert.rejects(api.getTaxonomy(), { code: 50001, httpStatus: 200 })
  await assert.rejects(api.createIntent({ achievement_id: 'a-1', demand_id: 'd-1' }), {
    code: 40901,
    httpStatus: 200,
  })
  await assert.rejects(
    api.getTaxonomy(),
    (error) => error instanceof ApiError && error.code === 50301 && error.httpStatus === undefined,
  )
  assert.deepEqual(unauthorized, ['expired-token'])
})

test('HTTP encodes path and query values while preserving false and zero', async () => {
  const requests: URL[] = []
  const api = new HttpApi({
    baseUrl: 'https://api.example.invalid/api/v1/',
    fetch: async (input) => {
      requests.push(new URL(String(input)))
      return success({})
    },
  })
  await api.getAchievements({
    page: 2,
    page_size: 30,
    keyword: '电解质 & Li+',
    publication_status: 'mine',
    trl_min: undefined,
  })
  await api.getDemands({ status: 'active', cooperation_mode: 'joint_development', required_trl: 5 })
  await api.getMatches('enterprise', 'demand/a?b', { min_score: 0, is_stale: false })
  await api.getMatches('research', '成果 1', { is_stale: true })
  assert.deepEqual(Object.fromEntries(requests[0].searchParams), {
    page: '2',
    page_size: '30',
    keyword: '电解质 & Li+',
    publication_status: 'mine',
  })
  assert.deepEqual(Object.fromEntries(requests[1].searchParams), {
    status: 'active',
    cooperation_mode: 'joint_development',
    required_trl: '5',
  })
  assert.equal(requests[2].pathname, '/api/v1/demands/demand%2Fa%3Fb/matches')
  assert.deepEqual(Object.fromEntries(requests[2].searchParams), {
    min_score: '0',
    is_stale: 'false',
  })
  assert.equal(requests[3].pathname, '/api/v1/achievements/%E6%88%90%E6%9E%9C%201/matches')
})

test('HTTP returns correctly paginated intent status results when S-11 ignores the status filter', async () => {
  const rows = Array.from({ length: 103 }, (_, index) => ({
    intent_id: String(index),
    status: index % 2 ? 'declined' : 'confirmed',
  }))
  const requests: URLSearchParams[] = []
  const api = new HttpApi({
    fetch: async (input) => {
      const query = new URL(String(input), 'https://api.example.invalid').searchParams
      requests.push(query)
      const page = Number(query.get('page'))
      const page_size = Number(query.get('page_size'))
      return success({
        items: rows.slice((page - 1) * page_size, page * page_size),
        pagination: {
          page,
          page_size,
          total: rows.length,
          total_pages: Math.ceil(rows.length / page_size),
        },
      })
    },
  })
  const response = await api.listIntents({
    page: 26,
    page_size: 2,
    status: 'confirmed',
    demand_id: 'd-1',
    achievement_id: 'a-1',
  })
  assert.deepEqual(response.data.pagination, { page: 26, page_size: 2, total: 52, total_pages: 26 })
  assert.deepEqual(
    response.data.items.map((item) => item.intent_id),
    ['100', '102'],
  )
  assert.equal(requests.length, 3)
  assert.deepEqual(
    requests.map((query) => query.get('page')),
    ['26', '1', '2'],
  )
  for (const query of requests) {
    assert.equal(query.get('status'), 'confirmed')
    assert.equal(query.get('demand_id'), 'd-1')
    assert.equal(query.get('achievement_id'), 'a-1')
  }
})

test('HTTP normalizes both intent contact formats and respects explicit disclosure flags', async () => {
  const actual: IntentContactResponse = {
    intent_id: 'intent-1',
    status: 'confirmed',
    is_simulated: true,
    researcher_contact: { name: '科研方演示联系人', email: 'researcher@example.invalid' },
    enterprise_contact: { name: '企业方演示联系人', email: 'enterprise@example.invalid' },
  }
  const simple: IntentContactResponse = {
    intent_id: 'intent-2',
    is_mock: true,
    email: 'demo@example.invalid',
    phone: '000-0000',
  }
  const api = new HttpApi({
    fetch: async (input) => success(String(input).endsWith('/intent-1/contact') ? actual : simple),
  })
  const contacts = (await api.getIntentContact('intent-1')).data
  assert.deepEqual(contacts, {
    intent_id: 'intent-1',
    is_simulated: true,
    contacts: [
      { role: 'researcher', ...actual.researcher_contact },
      { role: 'enterprise', ...actual.enterprise_contact },
    ],
  })
  assert.deepEqual((await api.getIntentContact('intent-2')).data, {
    intent_id: 'intent-2',
    is_simulated: true,
    contacts: [{ email: simple.email, phone: simple.phone }],
  })
  assert.deepEqual(normalizeIntentContact(contacts), contacts)
  assert.equal(isContactRevealed({ status: 'confirmed' }), true)
  assert.equal(isContactRevealed({ status: 'confirmed', contact_revealed: false }), false)
  assert.equal(isContactRevealed({ status: 'declined' }), false)
})

test('auth restores a saved token, clears on HTTP 401, and logs in and out', async (t) => {
  const user: LoginData['user'] = {
    user_id: 'sample-user',
    username: 'sample-user',
    role: 'researcher',
    display_name: '测试用户',
  }
  setAccessToken('restore-token')
  t.after(() => setAccessToken(null))
  const fetch = t.mock.method(
    globalThis,
    'fetch',
    async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/login')) return success({ token: 'login-token', user })
      if (
        new Headers(init?.headers).get('Authorization') === 'Bearer restore-token' &&
        String(input).endsWith('/auth/me')
      ) {
        return success(user)
      }
      return failure(401, 'Session expired')
    },
  )
  const { api } = await import('./index')
  const { auth, login, logout, restoreSession } = await import('../auth')
  assert.equal(auth.initialized, false)
  await Promise.all([restoreSession(), restoreSession()])
  assert.equal(fetch.mock.callCount(), 1)
  assert.equal(auth.initialized, true)
  assert.equal(auth.isAuthenticated, true)
  assert.equal(auth.isResearcher, true)
  assert.equal(auth.isEnterprise, false)
  assert.deepEqual(auth.user, user)
  await assert.rejects(api.getPipelineRun('run-1'), apiError(401))
  assert.equal(getAccessToken(), null)
  assert.equal(auth.user, null)
  assert.equal(auth.sessionExpired, true)
  await login('sample-user', 'test-only')
  assert.equal(auth.token, 'login-token')
  assert.equal(auth.sessionExpired, false)
  assert.equal(getAccessToken(), 'login-token')
  logout()
  assert.equal(auth.token, null)
  assert.equal(auth.isAuthenticated, false)
  assert.equal(getAccessToken(), null)
})

test('catalog caches successful loads and refreshes publication data on demand', async (t) => {
  const requests: URL[] = []
  let publisher: string | null = null
  const fetch = t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://api.example.invalid')
    requests.push(url)
    if (url.pathname.endsWith('/taxonomy')) {
      if (requests.filter((entry) => entry.pathname === url.pathname).length === 1) {
        return failure(503, 'Taxonomy unavailable')
      }
      return success(fixtures.taxonomy)
    }
    const page = Number(url.searchParams.get('page'))
    const page_size = Number(url.searchParams.get('page_size'))
    const seen = (page - 1) * page_size
    return success({
      items: Array.from({ length: Math.min(page_size, 101 - seen) }, (_, index) => ({
        ...fixtures.achievements[0],
        achievement_id: `achievement-${seen + index + 1}`,
        publisher_user_id: publisher,
      })),
      pagination: { page, page_size, total: 101, total_pages: Math.ceil(101 / page_size) },
    })
  })
  const { catalog, loadCatalogObjects, loadTaxonomy } = await import('../catalog')
  assert.equal(fetch.mock.callCount(), 0)
  await assert.rejects(loadTaxonomy(), apiError(503))
  await Promise.all([loadTaxonomy(), loadTaxonomy(), loadCatalogObjects('research')])
  await loadTaxonomy()
  assert.equal(requests.filter((entry) => entry.pathname.endsWith('/taxonomy')).length, 2)
  assert.equal(catalog.taxonomy?.taxonomy_version, fixtures.taxonomy.taxonomy_version)
  assert.equal(catalog.achievements.length, 101)
  assert.equal(catalog.achievements.at(-1)?.achievement_id, 'achievement-101')

  publisher = 'user_research_demo'
  await loadCatalogObjects('research')
  assert.equal(catalog.achievements[0].publisher_user_id, null)
  const refresh = loadCatalogObjects('research', { force: true })
  assert.equal(loadCatalogObjects('research'), refresh)
  await refresh
  assert.equal(catalog.achievements[0].publisher_user_id, publisher)
  assert.equal(requests.filter((entry) => entry.pathname.endsWith('/achievements')).length, 4)
})

test('Mock runs the publish and intent workflows for both demo accounts', async () => {
  const api = new MockApi(fixtures, 0)
  const achievement = fixtures.achievements[0]
  const [demand, secondDemand] = fixtures.demands
  const achievement_id = achievement.achievement_id
  const demand_id = demand.demand_id
  const publishAchievement = { achievement_id, updates: {} }
  const publishDemand = { demand_id, updates: {} }
  const pair = { achievement_id, demand_id }

  await assert.rejects(api.login('wrong_demo', 'test-only'), apiError(401))
  await assert.rejects(api.login('research_demo', ''), apiError(401))
  await assert.rejects(api.me(), apiError(401))
  await assert.rejects(api.listIntents(), apiError(401))
  assert.throws(() => api.getAchievements({ publication_status: 'mine' }), apiError(401))
  const researcher = (await api.login('research_demo', 'test-only')).data.user
  assert.deepEqual((await api.me()).data, researcher)
  assert.equal(researcher.user_id, 'user_research_demo')
  assert.equal(researcher.role, 'researcher')
  await assert.rejects(api.publishDemand(publishDemand), apiError(403))
  await assert.rejects(api.createIntent(pair), apiError(403))
  const before = await api.getAchievements({
    publication_status: 'unpublished',
    keyword: achievement.title_original.toUpperCase(),
    tech_field: achievement.tech_fields[0].code,
  })
  assert.equal(before.data.items[0].achievement_id, achievement_id)
  assert.equal(before.data.items[0].trl, null)
  assert.equal((await api.getAchievements({ trl_max: 9 })).data.pagination.total, 0)
  const { run_id } = (await api.publishAchievement(publishAchievement)).data
  await assert.rejects(api.publishAchievement(publishAchievement), apiError(409))
  const published = (await api.getAchievement(achievement_id)).data
  assert.equal(published.clean_status, 'published')
  assert.equal(published.publisher_user_id, researcher.user_id)
  assert.ok(published.published_at)
  assert.equal((await api.getAchievements({ publication_status: 'mine' })).data.pagination.total, 1)
  assert.equal(
    (await api.getAchievements({ publication_status: 'unpublished' })).data.pagination.total,
    fixtures.achievements.length - 1,
  )
  await assert.rejects(api.createIntent(pair), apiError(409))
  const [running, finished] = await Promise.all([
    api.getPipelineRun(run_id),
    api.getPipelineRun(run_id),
  ])
  assert.equal(running.data.status, 'running')
  assert.equal(running.data.finished_at, null)
  assert.equal(finished.data.status, 'success')
  assert.ok(finished.data.finished_at)

  const enterprise = (await api.login('enterprise_demo', 'test-only')).data.user
  assert.equal(enterprise.user_id, 'user_enterprise_demo')
  assert.equal(enterprise.role, 'enterprise')
  await assert.rejects(api.publishAchievement(publishAchievement), apiError(403))
  const demandRun = (await api.publishDemand(publishDemand)).data.run_id
  await assert.rejects(api.publishDemand(publishDemand), apiError(409))
  assert.equal((await api.getPipelineRun(demandRun)).data.status, 'running')
  assert.equal((await api.getPipelineRun(demandRun)).data.status, 'success')
  assert.deepEqual(
    (
      await api.getDemands({
        publication_status: 'mine',
        keyword: demand.title,
        tech_field: demand.tech_fields[0],
        required_trl: demand.required_trl,
        region: demand.region,
        status: 'active',
        cooperation_mode: demand.cooperation_modes[0],
      })
    ).data.items.map((item) => item.demand_id),
    [demand_id],
  )
  const demandDetail = (await api.getDemand(demand_id)).data
  assert.equal(demandDetail.publisher_user_id, enterprise.user_id)
  assert.ok(demandDetail.published_at)
  assert.equal((await api.getAchievements({ publication_status: 'mine' })).data.pagination.total, 0)
  assert.equal(
    (await api.getDemands({ publication_status: 'unpublished' })).data.pagination.total,
    fixtures.demands.length - 1,
  )

  const intent = (await api.createIntent(pair)).data
  assert.equal(intent.status, 'expressed')
  assert.equal(intent.initiator_user_id, enterprise.user_id)
  assert.equal(intent.achievement_title, achievement.title_original)
  assert.equal(intent.demand_title, demand.title)
  assert.equal(isContactRevealed(intent), false)
  await assert.rejects(api.createIntent(pair), apiError(409))
  await assert.rejects(api.confirmIntent(intent.intent_id), apiError(403))
  await assert.rejects(api.declineIntent(intent.intent_id), apiError(403))
  await assert.rejects(api.getIntentContact(intent.intent_id), apiError(403))
  await api.publishDemand({ demand_id: secondDemand.demand_id, updates: {} })
  const second = (await api.createIntent({ achievement_id, demand_id: secondDemand.demand_id }))
    .data
  await api.login('research_demo', 'test-only')
  const list = await api.listIntents({ achievement_id, status: 'expressed', page_size: 1 })
  assert.equal(list.data.items.length, 1)
  assert.equal(list.data.pagination.total, 2)
  assert.equal(list.data.pagination.total_pages, 2)
  const confirmed = (await api.confirmIntent(intent.intent_id)).data
  assert.equal(confirmed.status, 'confirmed')
  assert.equal(confirmed.contact_revealed, true)
  await assert.rejects(api.declineIntent(intent.intent_id), apiError(409))
  const declined: Intent = (await api.declineIntent(second.intent_id)).data
  assert.equal(declined.status, 'declined')
  assert.equal(declined.contact_revealed, false)
  await assert.rejects(api.getIntentContact(second.intent_id), apiError(403))
  const contact = (await api.getIntentContact(intent.intent_id)).data
  assert.equal(contact.is_simulated, true)
  assert.deepEqual(
    contact.contacts.map((party) => party.email),
    ['researcher@example.invalid', 'enterprise@example.invalid'],
  )
  await api.login('enterprise_demo', 'test-only')
  assert.deepEqual((await api.getIntentContact(intent.intent_id)).data, contact)
  await assert.rejects(api.getIntentContact(second.intent_id), apiError(403))
  assert.equal(
    (await api.listIntents({ ...pair, status: 'confirmed' })).data.items[0].intent_id,
    intent.intent_id,
  )
  assert.equal((await api.listIntents({ ...pair, status: 'declined' })).data.pagination.total, 0)
  assert.equal(achievement.publisher_user_id, undefined)
  assert.equal(demand.publisher_user_id, undefined)
})

test('Mock restores publication, intent, and pipeline state from browser sessionStorage', async () => {
  const store = new Map<string, string>()
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      sessionStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
      },
    },
  })
  try {
    const api = new MockApi(fixtures, 0, getAccessToken)
    const achievement_id = fixtures.achievements[0].achievement_id
    const { demand_id } = fixtures.demands[0]
    const researcher = (await api.login('research_demo', 'test-only')).data
    setAccessToken(researcher.token)
    const { run_id } = (await api.publishAchievement({ achievement_id, updates: {} })).data
    assert.equal((await api.getPipelineRun(run_id)).data.status, 'running')
    const enterprise = (await api.login('enterprise_demo', 'test-only')).data
    setAccessToken(enterprise.token)
    await api.publishDemand({ demand_id, updates: {} })
    const { intent_id } = (await api.createIntent({ achievement_id, demand_id })).data
    assert.equal(store.get('aim_access_token'), enterprise.token)
    const reloaded = new MockApi(fixtures, 0, getAccessToken)
    assert.deepEqual((await reloaded.me()).data, enterprise.user)
    assert.equal(
      (await reloaded.getDemands({ publication_status: 'mine' })).data.pagination.total,
      1,
    )
    assert.equal((await reloaded.listIntents()).data.items[0].intent_id, intent_id)
    assert.equal((await reloaded.getPipelineRun(run_id)).data.status, 'success')
    setAccessToken(researcher.token)
    await reloaded.confirmIntent(intent_id)
    setAccessToken(enterprise.token)
    const reopened = new MockApi(fixtures, 0, getAccessToken)
    assert.equal((await reopened.getIntentContact(intent_id)).data.contacts.length, 2)
  } finally {
    setAccessToken(null)
    Reflect.deleteProperty(globalThis, 'window')
  }
})
