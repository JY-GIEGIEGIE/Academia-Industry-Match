import { getCurrentScope, onScopeDispose, ref } from 'vue'
import { api, ApiError } from '../api'
import type { PipelineRun } from '../types'

type FinishedStatus = 'success' | 'partial'
type Phase = 'idle' | 'queued' | 'paused' | 'unavailable' | PipelineRun['status']
interface Options {
  pollInterval?: number
  timeout?: number
  fetcher?: (id: string) => Promise<PipelineRun>
  onFinished?: (status: FinishedStatus) => void
}

export function usePipelineRun({
  pollInterval = 2000,
  timeout = 60000,
  fetcher = async (id) => (await api.getPipelineRun(id)).data,
  onFinished,
}: Options = {}) {
  const phase = ref<Phase>('idle')
  const querying = ref(false)
  const message = ref('')
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let deadlineTimer: ReturnType<typeof setTimeout> | undefined
  let runId: string | undefined
  let startedAt = 0
  let revision = 0

  function clearTimers() {
    clearTimeout(pollTimer)
    clearTimeout(deadlineTimer)
    pollTimer = deadlineTimer = undefined
  }

  function stop() {
    revision++
    runId = undefined
    querying.value = false
    clearTimers()
  }

  async function query(id: string, automatic: boolean) {
    if (querying.value) return
    const request = revision
    const queriedAt = Date.now()
    querying.value = true
    let finished: FinishedStatus | undefined
    try {
      const run = await fetcher(id)
      if (request !== revision) return
      phase.value = run.status === 'running' && !automatic ? 'paused' : run.status
      message.value = ''
      if (run.status === 'success' || run.status === 'partial') finished = run.status
    } catch (error) {
      if (request !== revision) return
      const notFound = error instanceof ApiError && error.httpStatus === 404
      phase.value =
        notFound && automatic && Date.now() - startedAt < 10000 ? 'queued' : 'unavailable'
      message.value = notFound
        ? '暂未查询到匹配任务，请稍后刷新状态。'
        : '查询匹配状态失败，请稍后刷新。'
    } finally {
      if (request === revision) querying.value = false
    }
    if (automatic && (phase.value === 'running' || phase.value === 'queued')) {
      const delay = Math.max(0, pollInterval - (Date.now() - queriedAt))
      pollTimer = setTimeout(() => void query(id, true), delay)
    } else {
      clearTimers()
      if (finished) onFinished?.(finished)
    }
  }

  function start(id: string) {
    stop()
    runId = id
    startedAt = Date.now()
    phase.value = 'queued'
    message.value = ''
    deadlineTimer = setTimeout(() => {
      revision++
      clearTimers()
      querying.value = false
      phase.value = 'paused'
    }, timeout)
    void query(id, true)
  }

  async function refresh() {
    if (runId && ['paused', 'unavailable', 'failed'].includes(phase.value)) {
      await query(runId, false)
    }
  }

  if (getCurrentScope()) onScopeDispose(stop)
  return { phase, message, querying, start, stop, refresh }
}
