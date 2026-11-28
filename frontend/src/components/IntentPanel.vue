<script setup lang="ts">
import { computed, onScopeDispose, ref, useId, watch } from 'vue'
import { api } from '../api'
import { auth } from '../auth'
import { intentErrorMessage, useIntentActions } from '../composables/useIntentActions'
import type { Achievement, Demand, Intent } from '../types'
import { getIntentActionState, intentCreationGuidance, intentInitiatorText } from '../utils/display'
import IntentContactCard from './IntentContactCard.vue'

const props = defineProps<{ achievement: Achievement; demand: Demand; matchId: string }>()
const headingId = useId()
const intent = ref<Intent | null>(null)
const loading = ref(true)
const loadError = ref('')
const pair = computed(() => ({
  achievement_id: props.achievement.achievement_id,
  demand_id: props.demand.demand_id,
}))
const scope = computed(() =>
  JSON.stringify([props.matchId, pair.value.achievement_id, pair.value.demand_id]),
)
const { pending, actionError, runIntentAction } = useIntentActions(() => scope.value)
const actions = computed(() =>
  getIntentActionState({
    intent: intent.value,
    currentUserId: auth.user?.user_id,
    achievementPublisherId: props.achievement.publisher_user_id,
    demandPublisherId: props.demand.publisher_user_id,
  }),
)
const creationGuidance = computed(() =>
  auth.user
    ? intentCreationGuidance(
        auth.user.role,
        auth.user.user_id,
        auth.isResearcher ? props.achievement.publisher_user_id : props.demand.publisher_user_id,
      )
    : null,
)
const otherParty = computed(() => (auth.isResearcher ? '企业方' : '科研方'))
let revision = 0

async function load() {
  const request = ++revision
  const session = auth.token
  const context = scope.value
  const isCurrent = () => request === revision && context === scope.value && session === auth.token
  intent.value = null
  loadError.value = ''
  actionError.value = ''
  loading.value = Boolean(session)
  if (!session) return
  const { achievement_id, demand_id } = pair.value
  try {
    const { data } = await api.listIntents({ achievement_id, demand_id, page_size: 20 })
    if (isCurrent()) {
      intent.value =
        data.items.find(
          (item) => item.achievement_id === achievement_id && item.demand_id === demand_id,
        ) ?? null
    }
  } catch (error) {
    if (isCurrent()) loadError.value = intentErrorMessage(error, '暂时无法查询此配对的合作意向')
  } finally {
    if (isCurrent()) loading.value = false
  }
}

function create() {
  if (!actions.value.canCreate) return
  const payload = pair.value
  return runIntentAction('create', scope.value, () => api.createIntent(payload), load)
}

function respond(action: 'confirm' | 'decline') {
  const id = intent.value?.intent_id
  if (!id || !actions.value.canRespond) return
  return runIntentAction(
    action,
    id,
    () => (action === 'confirm' ? api.confirmIntent(id) : api.declineIntent(id)),
    load,
  )
}

watch([scope, () => auth.token], load, { immediate: true })
onScopeDispose(() => revision++)
</script>

<template>
  <section class="intent-panel tool-panel" :aria-labelledby="headingId" :aria-busy="loading">
    <header class="intent-panel-heading">
      <h2 :id="headingId">合作意向</h2>
      <RouterLink class="intent-link" to="/intents">查看全部合作意向</RouterLink>
    </header>

    <p v-if="loading" class="intent-note" role="status">正在查询此配对的合作意向…</p>
    <template v-else-if="loadError">
      <el-alert :title="loadError" type="error" :closable="false" show-icon />
      <div><el-button @click="load">重试</el-button></div>
    </template>
    <template v-else>
      <div v-if="actionError" class="intent-error">
        <el-alert :title="actionError" type="error" :closable="false" show-icon />
        <div><el-button size="small" @click="load">刷新状态</el-button></div>
      </div>

      <template v-if="!intent">
        <div v-if="actions.canCreate" class="intent-actions">
          <el-button type="primary" :loading="pending?.action === 'create'" @click="create">
            表达合作意向
          </el-button>
          <p class="intent-note">双方确认后可查看演示联系方式。</p>
        </div>
        <p v-else-if="creationGuidance" class="intent-note">
          {{ creationGuidance.message }}
          <RouterLink v-if="creationGuidance.publishLabel" class="intent-link" to="/publish">
            {{ creationGuidance.publishLabel }}
          </RouterLink>
        </p>
      </template>
      <template v-else>
        <div class="intent-status" aria-live="polite">
          <el-tag
            :type="intent.status === 'confirmed' ? 'success' : 'info'"
            effect="light"
            disable-transitions
          >
            {{ actions.statusText }}
          </el-tag>
          <span v-if="auth.user" class="intent-note">{{
            intentInitiatorText(auth.user.role, actions.isInitiator, intent.status)
          }}</span>
          <p v-if="intent.status === 'expressed' && actions.isInitiator" class="intent-note">
            等待{{ otherParty }}登录确认后可查看演示联系方式。
          </p>
          <p
            v-else-if="intent.status === 'declined' || intent.status === 'closed'"
            class="intent-note"
          >
            此状态下不披露联系方式。
          </p>
          <p
            v-else-if="intent.status === 'confirmed' && !actions.canRevealContact"
            class="intent-note"
          >
            暂不可查看联系方式（需双方确认且具访问权限）
          </p>
        </div>
        <div v-if="actions.canRespond" class="intent-actions">
          <el-button
            type="primary"
            :loading="pending?.action === 'confirm'"
            :disabled="Boolean(pending)"
            @click="respond('confirm')"
            >确认合作意向</el-button
          >
          <el-button
            type="danger"
            plain
            :loading="pending?.action === 'decline'"
            :disabled="Boolean(pending)"
            @click="respond('decline')"
            >拒绝意向</el-button
          >
        </div>
        <IntentContactCard v-if="actions.canRevealContact" :intent-id="intent.intent_id" />
      </template>
    </template>
  </section>
</template>

<style scoped>
.intent-panel {
  display: grid;
  gap: 12px;
  margin-bottom: 24px;
}
.intent-panel-heading,
.intent-actions,
.intent-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.intent-panel-heading {
  justify-content: space-between;
}
.intent-link {
  color: var(--accent);
  font-size: 14px;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.intent-note {
  color: var(--muted);
  font-size: 14px;
}
.intent-actions .el-button + .el-button {
  margin-left: 0;
}
.intent-error {
  display: grid;
  gap: 8px;
}
</style>
