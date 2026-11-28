import assert from 'node:assert/strict'
import test, { type TestContext } from 'node:test'
import { effectScope } from 'vue'
import { ApiError } from '../api'
import type { PipelineRun } from '../types'
import { usePipelineRun } from './usePipelineRun'

function result(status: PipelineRun['status'], id: string): PipelineRun {
  return { run_id: id, stage: 'match', status, started_at: null, finished_at: null }
}

function clock(t: TestContext) {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'] })
  return async (milliseconds = 0) => {
    t.mock.timers.tick(milliseconds)
    await Promise.resolve()
  }
}

const notFound = new ApiError(40401, 'Task not found', 404)

test('polls immediately, then every two seconds until success', async (t) => {
  const tick = clock(t)
  const requests: string[] = []
  const finished: string[] = []
  const tracker = usePipelineRun({
    fetcher: async (id) => {
      requests.push(id)
      return result(requests.length === 1 ? 'running' : 'success', id)
    },
    onFinished: (status) => finished.push(status),
  })
  tracker.start('run-1')
  assert.deepEqual(requests, ['run-1'])
  await tick()
  await tick(1999)
  assert.equal(tracker.phase.value, 'running')
  assert.equal(requests.length, 1)
  await tick(1)
  assert.equal(tracker.phase.value, 'success')
  assert.deepEqual(finished, ['success'])
  await tick(60000)
  assert.deepEqual(requests, ['run-1', 'run-1'])
  assert.equal(tracker.phase.value, 'success')
})

test('treats early HTTP 404s as queued and recovers on a later poll', async (t) => {
  const tick = clock(t)
  let calls = 0
  const tracker = usePipelineRun({
    fetcher: async (id) => {
      if (++calls <= 2) throw notFound
      return result('success', id)
    },
  })
  tracker.start('run-1')
  await tick()
  assert.equal(tracker.phase.value, 'queued')
  await tick(2000)
  assert.equal(tracker.phase.value, 'queued')
  await tick(2000)
  assert.equal(tracker.phase.value, 'success')
  assert.equal(calls, 3)
})

test('stops retrying HTTP 404s after the first ten seconds and offers a manual query', async (t) => {
  const tick = clock(t)
  let calls = 0
  const tracker = usePipelineRun({
    fetcher: async (id) => {
      if (++calls <= 6) throw notFound
      return result('success', id)
    },
  })
  tracker.start('run-1')
  await tick()
  for (let i = 0; i < 4; i++) {
    await tick(2000)
    assert.equal(tracker.phase.value, 'queued')
  }
  await tick(2000)
  assert.equal(tracker.phase.value, 'unavailable')
  await tick(60000)
  assert.equal(calls, 6)
  await tracker.refresh()
  assert.equal(tracker.phase.value, 'success')
})

for (const status of ['partial', 'failed'] as const) {
  test(`stops automatic polling on ${status}`, async (t) => {
    const tick = clock(t)
    const finished: string[] = []
    let calls = 0
    const tracker = usePipelineRun({
      pollInterval: 500,
      fetcher: async (id) => {
        calls++
        return result(calls === 1 ? 'running' : status, id)
      },
      onFinished: (complete) => finished.push(complete),
    })
    tracker.start('run-1')
    await tick()
    await tick(500)
    assert.equal(tracker.phase.value, status)
    await tick(60000)
    assert.equal(calls, 2)
    assert.deepEqual(finished, status === 'partial' ? ['partial'] : [])
    if (status === 'failed') {
      await tracker.refresh()
      assert.equal(calls, 3)
      assert.equal(tracker.phase.value, 'failed')
    }
  })
}

test('pauses at 60 seconds and keeps each manual refresh to a single query', async (t) => {
  const tick = clock(t)
  const finished: string[] = []
  let status: PipelineRun['status'] = 'running'
  let calls = 0
  const tracker = usePipelineRun({
    fetcher: async (id) => {
      calls++
      return result(status, id)
    },
    onFinished: (complete) => finished.push(complete),
  })
  tracker.start('run-1')
  await tick()
  for (let elapsed = 2000; elapsed < 60000; elapsed += 2000) await tick(2000)
  await tick(1999)
  assert.equal(tracker.phase.value, 'running')
  assert.equal(calls, 30)
  await tick(1)
  assert.equal(tracker.phase.value, 'paused')
  await tick(60000)
  assert.equal(calls, 30)
  await tracker.refresh()
  assert.equal(tracker.phase.value, 'paused')
  await tick(60000)
  assert.equal(calls, 31)
  status = 'success'
  await tracker.refresh()
  assert.equal(tracker.phase.value, 'success')
  assert.deepEqual(finished, ['success'])
  assert.equal(calls, 32)
})

test('an injected timeout pauses even when the in-flight request has not resolved', async (t) => {
  const tick = clock(t)
  const tracker = usePipelineRun({
    timeout: 250,
    fetcher: () => new Promise(() => {}),
  })
  tracker.start('run-1')
  await tick(250)
  assert.equal(tracker.phase.value, 'paused')
  assert.equal(tracker.querying.value, false)
})

test('stop clears the poll timer and the deadline timer', async (t) => {
  const tick = clock(t)
  let calls = 0
  const tracker = usePipelineRun({
    fetcher: async (id) => {
      calls++
      return result('running', id)
    },
  })
  tracker.start('run-1')
  await tick()
  tracker.stop()
  await tick(60000)
  assert.equal(calls, 1)
  assert.equal(tracker.phase.value, 'running')
})

test('scope disposal ignores late responses and never schedules another poll', async (t) => {
  const tick = clock(t)
  let resolve!: (run: PipelineRun) => void
  let calls = 0
  const scope = effectScope()
  const tracker = scope.run(() =>
    usePipelineRun({
      fetcher: () => {
        calls++
        return new Promise((settle) => {
          resolve = settle
        })
      },
    }),
  )!
  tracker.start('run-1')
  scope.stop()
  resolve(result('running', 'run-1'))
  await tick()
  await tick(60000)
  assert.equal(tracker.phase.value, 'queued')
  assert.equal(tracker.querying.value, false)
  assert.equal(calls, 1)
})
