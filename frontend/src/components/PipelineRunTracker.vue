<script setup lang="ts">
import { computed, watch } from 'vue'
import { usePipelineRun } from '../composables/usePipelineRun'
import { auth } from '../auth'
import { recommendationsRoute } from '../utils/recommendationsRoute'

const props = defineProps<{
  runId: string
  objectId: string
  title: string
}>()
const emit = defineEmits<{ finished: [] }>()
const { phase, message, querying, start, refresh } = usePipelineRun({
  onFinished: () => emit('finished'),
})
watch(() => props.runId, start, { immediate: true })
const recommendations = computed(() => {
  const route = recommendationsRoute(auth.isResearcher ? 'researcher' : 'enterprise')
  return { ...route, query: { ...route.query, object: props.objectId } }
})

const status = computed(() => {
  switch (phase.value) {
    case 'running':
      return { type: 'info', title: '匹配引擎执行中，请稍候…' } as const
    case 'success':
      return { type: 'success', title: '匹配已完成' } as const
    case 'partial':
      return { type: 'warning', title: '基础匹配已完成，部分精排已回退至基础结果' } as const
    case 'failed':
      return { type: 'error', title: '匹配任务执行失败' } as const
    case 'paused':
      return { type: 'warning', title: '任务仍在处理中，请稍候手动刷新' } as const
    case 'unavailable':
      return { type: 'warning', title: message.value } as const
    default:
      return { type: 'info', title: '任务排队启动中…' } as const
  }
})
</script>

<template>
  <section class="tool-panel run-tracker">
    <h2>匹配任务状态</h2>
    <p>{{ title }}</p>
    <div aria-live="polite">
      <el-alert :title="status.title" :type="status.type" :closable="false" show-icon />
    </div>
    <el-button
      v-if="phase === 'success' || phase === 'partial'"
      tag="router-link"
      type="primary"
      :to="recommendations"
    >
      前往查看推荐结果
    </el-button>
    <el-button
      v-else-if="phase === 'paused' || phase === 'unavailable' || phase === 'failed'"
      :loading="querying"
      @click="refresh"
    >
      {{ phase === 'failed' ? '重新查询状态' : '手动刷新状态' }}
    </el-button>
  </section>
</template>

<style scoped>
.run-tracker {
  display: grid;
  gap: 10px;
  overflow-wrap: anywhere;
}
.run-tracker p {
  color: var(--muted);
}
.run-tracker .el-button {
  justify-self: start;
}
</style>
