<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { api, isContactRevealed } from '../api'
import { auth } from '../auth'
import IntentContactCard from '../components/IntentContactCard.vue'
import { intentErrorMessage, useIntentActions } from '../composables/useIntentActions'
import type { Intent, IntentStatus } from '../types'
import { intentInitiatorText, intentStatusText, resolveIntentMatchId } from '../utils/display'

const PAGE_SIZE = 10
const filters: { value: IntentStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'expressed', label: '已表达' },
  { value: 'confirmed', label: '已确认' },
  { value: 'declined', label: '已拒绝' },
  { value: 'closed', label: '已关闭' },
]
const status = ref<IntentStatus | 'all'>('all')
const page = ref(1)
const total = ref(0)
const intents = ref<Intent[]>([])
const loading = ref(true)
const loadError = ref('')
const contactId = ref<string | null>(null)
const { pending, actionError, runIntentAction } = useIntentActions()
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
const publishLabel = computed(() => (auth.isResearcher ? '前往发布成果' : '前往发布需求'))
const recommendLabel = computed(() =>
  auth.isResearcher ? '去为你推荐查看适配需求' : '去为你推荐查看推荐成果',
)
let revision = 0

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未记录' : dateFormat.format(date)
}

function canViewContact(intent: Intent) {
  return Boolean(auth.user && intent.status === 'confirmed' && isContactRevealed(intent))
}

const contactOpen = computed({
  get: () =>
    !loading.value &&
    intents.value.some((intent) => intent.intent_id === contactId.value && canViewContact(intent)),
  set: (open) => {
    if (!open) contactId.value = null
  },
})

async function load() {
  const request = ++revision
  const session = auth.token
  const requestedPage = page.value
  const requestedStatus = status.value
  const isCurrent = () =>
    request === revision &&
    session === auth.token &&
    requestedPage === page.value &&
    requestedStatus === status.value
  contactId.value = null
  loadError.value = ''
  actionError.value = ''
  loading.value = Boolean(session)
  if (!session) {
    intents.value = []
    total.value = 0
    return
  }
  try {
    const { data } = await api.listIntents({
      page: requestedPage,
      page_size: PAGE_SIZE,
      status: requestedStatus === 'all' ? undefined : requestedStatus,
    })
    if (!isCurrent()) return
    const lastPage = Math.max(1, data.pagination.total_pages)
    if (requestedPage > lastPage) {
      page.value = lastPage
      return
    }
    intents.value = data.items
    total.value = data.pagination.total
  } catch (error) {
    if (!isCurrent()) return
    intents.value = []
    total.value = 0
    loadError.value = intentErrorMessage(error, '暂时无法加载合作意向，请重试')
  } finally {
    if (isCurrent()) loading.value = false
  }
}

function selectStatus(value: IntentStatus | 'all') {
  status.value = value
  page.value = 1
}

function canRespond(intent: Intent) {
  return Boolean(
    auth.user && intent.status === 'expressed' && intent.initiator_user_id !== auth.user.user_id,
  )
}

function respond(intent: Intent, action: 'confirm' | 'decline') {
  if (!canRespond(intent)) return
  const id = intent.intent_id
  return runIntentAction(
    action,
    id,
    () => (action === 'confirm' ? api.confirmIntent(id) : api.declineIntent(id)),
    load,
  )
}

watch([status, page, () => auth.token], load, { immediate: true })
onScopeDispose(() => revision++)
</script>

<template>
  <section class="tool-panel intents-page" aria-labelledby="intents-heading">
    <header>
      <h1 id="intents-heading">合作意向</h1>
      <p class="intent-note">查看你发出和收到的合作意向。双方确认后可查看演示联系方式。</p>
    </header>

    <div class="intents-toolbar">
      <div class="status-filter">
        <label class="field-label" for="intent-status-filter">意向状态</label>
        <el-select id="intent-status-filter" :model-value="status" @change="selectStatus">
          <el-option
            v-for="filter in filters"
            :key="filter.value"
            :value="filter.value"
            :label="filter.label"
          />
        </el-select>
      </div>
      <el-button :disabled="Boolean(pending)" :loading="loading" @click="load">刷新列表</el-button>
    </div>

    <div :aria-busy="loading" class="intents-results">
      <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />
      <p v-if="loading" class="loading-state" role="status">正在读取合作意向…</p>
      <div v-else-if="loadError" class="intent-load-error">
        <el-alert :title="loadError" type="error" :closable="false" show-icon />
        <div><el-button @click="load">重试</el-button></div>
      </div>
      <el-empty
        v-else-if="!intents.length"
        :description="status === 'all' ? '暂无合作意向' : '暂无符合该状态的合作意向'"
      >
        <div class="intent-row-actions empty-actions">
          <el-button tag="router-link" to="/recommendations" type="primary">{{
            recommendLabel
          }}</el-button>
          <el-button tag="router-link" to="/publish">{{ publishLabel }}</el-button>
        </div>
      </el-empty>
      <template v-else>
        <ul class="intent-list" aria-label="合作意向列表">
          <li v-for="intent in intents" :key="intent.intent_id" class="intent-row">
            <div class="intent-row-content">
              <div class="intent-tags">
                <el-tag
                  :type="intent.status === 'confirmed' ? 'success' : 'info'"
                  effect="light"
                  disable-transitions
                  >{{ intentStatusText[intent.status] }}</el-tag
                >
                <el-tag v-if="auth.user" type="info" effect="plain" disable-transitions>{{
                  intentInitiatorText(
                    auth.user.role,
                    intent.initiator_user_id === auth.user.user_id,
                    intent.status,
                  )
                }}</el-tag>
              </div>
              <dl class="intent-pair">
                <div>
                  <dt>{{ auth.isResearcher ? '我的成果' : '我的需求' }}</dt>
                  <dd>
                    {{
                      (auth.isResearcher ? intent.achievement_title : intent.demand_title) ||
                      '标题待补充'
                    }}
                  </dd>
                </div>
                <div>
                  <dt>{{ auth.isResearcher ? '企业需求' : '科研成果' }}</dt>
                  <dd>
                    {{
                      (auth.isResearcher ? intent.demand_title : intent.achievement_title) ||
                      '标题待补充'
                    }}
                  </dd>
                </div>
              </dl>
              <p class="intent-dates">
                <span
                  >创建于
                  <time :datetime="intent.created_at">{{
                    formatDate(intent.created_at)
                  }}</time></span
                >
                <span
                  >更新于
                  <time :datetime="intent.updated_at">{{
                    formatDate(intent.updated_at)
                  }}</time></span
                >
              </p>
            </div>
            <div class="intent-row-actions">
              <el-button
                tag="router-link"
                :to="{ name: 'match-detail', params: { id: resolveIntentMatchId(intent) } }"
                >查看匹配详情</el-button
              >
              <template v-if="canRespond(intent)">
                <el-button
                  type="primary"
                  :loading="pending?.id === intent.intent_id && pending.action === 'confirm'"
                  :disabled="Boolean(pending)"
                  @click="respond(intent, 'confirm')"
                  >确认合作</el-button
                >
                <el-button
                  type="danger"
                  plain
                  :loading="pending?.id === intent.intent_id && pending.action === 'decline'"
                  :disabled="Boolean(pending)"
                  @click="respond(intent, 'decline')"
                  >拒绝</el-button
                >
              </template>
              <el-button
                v-if="canViewContact(intent)"
                type="primary"
                plain
                @click="contactId = intent.intent_id"
                >查看演示联系方式</el-button
              >
            </div>
          </li>
        </ul>
        <el-pagination
          v-model:current-page="page"
          :page-size="PAGE_SIZE"
          :total="total"
          :pager-count="5"
          layout="prev, pager, next"
          aria-label="合作意向分页"
        />
      </template>
    </div>

    <el-dialog
      v-model="contactOpen"
      title="演示联系方式"
      width="min(620px, calc(100% - 32px))"
      append-to-body
      destroy-on-close
      class="intent-contact-dialog"
    >
      <IntentContactCard v-if="contactOpen && contactId" :intent-id="contactId" />
    </el-dialog>
  </section>
</template>

<style scoped>
.intents-page,
.intents-results,
.intent-load-error {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.intents-page header p {
  margin-top: 6px;
}
.intent-note,
.intent-dates,
.intent-pair dt {
  color: var(--muted);
  font-size: 14px;
}
.intents-toolbar,
.status-filter,
.intent-tags,
.intent-dates,
.intent-row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.intents-toolbar {
  justify-content: space-between;
  padding: 12px 0;
  border-block: 1px solid var(--line);
}
.status-filter .field-label {
  margin: 0;
}
.status-filter .el-select {
  width: 126px;
}
.intent-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.intent-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px 20px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.intent-pair {
  display: grid;
  gap: 4px;
  margin: 8px 0;
}
.intent-pair div {
  display: grid;
  grid-template-columns: 4em minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
}
.intent-pair dd {
  margin: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.intent-dates {
  font-size: 12px;
}
.intent-row-actions {
  gap: 8px;
}
.intent-row-actions .el-button + .el-button {
  margin-left: 0;
}
.empty-actions,
.intents-page .el-pagination {
  justify-content: center;
}
:global(.intent-contact-dialog) {
  --el-dialog-border-radius: 6px;
}
@media (max-width: 760px) {
  .intent-row {
    grid-template-columns: minmax(0, 1fr);
    padding: 12px;
  }
  .intent-row-actions .el-button {
    padding-inline: 10px;
  }
}
</style>
