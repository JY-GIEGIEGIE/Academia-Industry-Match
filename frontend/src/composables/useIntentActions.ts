import { ElMessage, ElMessageBox } from 'element-plus'
import { onScopeDispose, ref } from 'vue'
import { ApiError } from '../api/error'
import { auth } from '../auth'

type IntentAction = 'create' | 'confirm' | 'decline'
const successMessages = {
  confirm: '已确认合作意向',
  decline: '已拒绝合作意向',
}
const errorMessages = {
  create: '暂时无法表达合作意向，请重试',
  confirm: '暂时无法确认合作意向，请重试',
  decline: '暂时无法拒绝合作意向，请重试',
}

export function hasApiStatus(error: unknown, status: number): boolean {
  return (
    error instanceof ApiError &&
    (error.httpStatus === status ||
      error.code === status ||
      Math.floor(error.code / 100) === status)
  )
}

export function intentErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && /[\u3400-\u9fff]/.test(error.message)
    ? error.message
    : fallback
}

export function useIntentActions(scope: () => string = () => '') {
  const pending = ref<{ action: IntentAction; id: string } | null>(null)
  const actionError = ref('')
  let active = true
  onScopeDispose(() => {
    active = false
  })

  async function runIntentAction(
    action: IntentAction,
    id: string,
    request: () => Promise<unknown>,
    refresh: () => Promise<void>,
  ) {
    const session = auth.token
    const context = scope()
    const isCurrent = () => active && session === auth.token && context === scope()
    if (!session || pending.value) return
    pending.value = { action, id }
    actionError.value = ''
    try {
      if (action === 'decline') {
        const accepted = await ElMessageBox.confirm(
          '拒绝后将不披露演示联系方式。',
          '拒绝合作意向',
          {
            confirmButtonText: '确认拒绝',
            cancelButtonText: '取消',
            type: 'warning',
          },
        ).then(
          () => true,
          () => false,
        )
        if (!accepted || !isCurrent()) return
      }
      await request()
      if (!isCurrent()) return
      const otherParty = auth.isResearcher ? '企业方' : '科研方'
      ElMessage.success(
        action === 'create' ? `已表达合作意向，等待${otherParty}确认` : successMessages[action],
      )
      await refresh()
    } catch (error) {
      if (!isCurrent()) return
      let fallback = errorMessages[action]
      if (hasApiStatus(error, 403)) fallback = '当前账号没有权限执行此操作'
      if (hasApiStatus(error, 409)) {
        fallback =
          action === 'create'
            ? '此配对的发布或意向状态已变化，请刷新后查看。'
            : '该合作意向状态已变化，请刷新后查看。'
      }
      actionError.value = hasApiStatus(error, 409) ? fallback : intentErrorMessage(error, fallback)
    } finally {
      pending.value = null
    }
  }

  return { pending, actionError, runIntentAction }
}
