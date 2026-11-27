import assert from 'node:assert/strict'
import test from 'node:test'
import { recommendationsRoute } from './recommendationsRoute'

test('recommendation links get a default view from the signed-in role', () => {
  assert.deepEqual(recommendationsRoute('researcher'), {
    path: '/recommendations',
    query: { view: 'research' },
  })
  assert.deepEqual(recommendationsRoute('enterprise'), {
    path: '/recommendations',
    query: { view: 'enterprise' },
  })
})

test('an incompatible view drops its object without losing the other filters', () => {
  for (const view of ['enterprise', 'other', undefined, ['research', 'enterprise']]) {
    const context = { view, object: 'dem_005', min_score: '80', is_stale: 'true' }
    assert.deepEqual(recommendationsRoute('researcher', context).query, {
      view: 'research',
      min_score: '80',
      is_stale: 'true',
    })
    assert.equal(context.object, 'dem_005')
  }
  assert.deepEqual(
    recommendationsRoute('enterprise', { view: 'research', object: 'ach_123' }).query,
    { view: 'enterprise' },
  )
})

test('returning to the same view restores the selected object, filters, and page', () => {
  const query = { view: 'research', object: 'ach_123', min_score: '80', page: '2' }
  assert.deepEqual(recommendationsRoute('researcher', query).query, query)
})
