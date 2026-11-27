<script setup lang="ts">
import { computed, nextTick, onScopeDispose, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '../api'
import type { PublicationStatus } from '../api'
import { auth } from '../auth'
import {
  label,
  labels,
  loadAchievements,
  loadCatalogObjects,
  loadDemands,
  loadObject,
  loadTaxonomy,
  safeSource,
} from '../catalog'
import PipelineRunTracker from '../components/PipelineRunTracker.vue'
import type {
  Achievement,
  AchievementSummary,
  Demand,
  DemandSummary,
  Perspective,
  Taxonomy,
} from '../types'

type RecordSummary = AchievementSummary | DemandSummary
type PublicationState = 'available' | 'mine' | 'claimed'
const route = useRoute()
const research = computed(() => auth.isResearcher)
const view = computed<Perspective>(() => (research.value ? 'research' : 'enterprise'))
const ownRoute = computed(() => ({
  name: research.value ? 'publish-achievement' : 'publish-demand',
}))
const allowed = computed(() => route.name === 'publish' || route.name === ownRoute.value.name)
const heading = computed(() => (research.value ? '发布科研成果' : '发布企业需求'))
const objectLabel = computed(() => (research.value ? '科研成果' : '企业需求'))
const mineLabel = computed(() => (research.value ? '前往发布成果' : '前往发布需求'))
const demoId = computed(() => (research.value ? 'ach_openalex_W4200428349' : 'dem_005'))

const filters: { value: PublicationStatus; label: string }[] = [
  { value: 'unpublished', label: '未发布' },
  { value: 'mine', label: '我已发布' },
  { value: 'all', label: '全部' },
]
const publicationLabels = {
  available: { text: '可发布', type: 'success' },
  mine: { text: '我已发布', type: 'primary' },
  claimed: { text: '已由他人发布', type: 'info' },
} as const
const reviewLabels: Record<string, string> = {
  pending: '待审核',
  approved: '已审核',
  rejected: '审核未通过',
  needs_review: '待复核',
}
const pageSize = 10
const page = ref(1)
const publicationFilter = ref<PublicationStatus>('unpublished')
const field = ref('')
const search = ref('')
const keyword = ref('')
const rows = ref<RecordSummary[]>([])
const total = ref(0)
const listBusy = ref(false)
const listError = ref('')
const taxonomy = ref<Taxonomy>()
const fields = computed(
  () => taxonomy.value?.dimensions.find((item) => item.dimension === 'tech_field')?.values ?? [],
)
const taxonomyError = ref('')
const selectedId = ref('')
const detail = ref<Achievement | Demand>()
const detailBusy = ref(false)
const detailError = ref('')
const publishBusy = ref(false)
const publishError = ref('')
const previewPanel = ref<HTMLElement>()
const trackersPanel = ref<HTMLElement>()
const runs = ref<{ id: string; objectId: string; title: string; view: Perspective }[]>([])
const selectedRun = computed(() => runs.value.some((run) => run.objectId === selectedId.value))
const achievement = computed(() =>
  detail.value && 'achievement_id' in detail.value ? detail.value : undefined,
)
const demand = computed(() =>
  detail.value && 'demand_id' in detail.value ? detail.value : undefined,
)
const source = computed(() => achievement.value && safeSource(achievement.value.source_url))
let listRevision = 0
let detailRevision = 0
let active = true

function recordId(record: RecordSummary) {
  return 'achievement_id' in record ? record.achievement_id : record.demand_id
}
function recordTitle(record: RecordSummary) {
  return 'achievement_id' in record ? record.title_original : record.title
}
function recordTrl(record: RecordSummary) {
  const trl = 'achievement_id' in record ? record.trl : record.required_trl
  return trl == null ? '待评估' : `TRL ${trl}`
}
function primaryField(record: RecordSummary) {
  if ('achievement_id' in record) {
    return record.tech_fields.find(({ is_primary }) => is_primary)?.code
  }
  return record.tech_fields[0]
}
function publicationState(record: RecordSummary): PublicationState {
  if (record.publisher_user_id == null) return 'available'
  return record.publisher_user_id === auth.user?.user_id ? 'mine' : 'claimed'
}
function recommendations(objectId: string) {
  return { path: '/recommendations', query: { view: view.value, object: objectId } }
}

async function fetchTaxonomy() {
  taxonomyError.value = ''
  try {
    taxonomy.value = await loadTaxonomy()
  } catch {
    taxonomyError.value = '技术领域标签暂时无法加载。'
  }
}

async function fetchList() {
  const request = ++listRevision
  if (!allowed.value) return
  const params = {
    page: page.value,
    page_size: pageSize,
    publication_status: publicationFilter.value,
    tech_field: field.value || undefined,
    keyword: research.value ? keyword.value || undefined : undefined,
  }
  listBusy.value = true
  listError.value = ''
  try {
    const { data } = await (research.value ? loadAchievements(params) : loadDemands(params))
    if (request !== listRevision) return
    total.value = data.pagination.total
    const lastPage = Math.max(1, data.pagination.total_pages)
    if (page.value > lastPage) {
      page.value = lastPage
      return
    }
    rows.value = data.items
  } catch {
    if (request !== listRevision) return
    rows.value = []
    total.value = 0
    listError.value = '数据池暂时无法加载，请重试。'
  } finally {
    if (request === listRevision) listBusy.value = false
  }
}

async function fetchDetail(id: string) {
  const request = ++detailRevision
  detailBusy.value = true
  detailError.value = ''
  try {
    const { data } = await loadObject(view.value, id)
    if (request === detailRevision) detail.value = data
  } catch {
    if (request === detailRevision) {
      detail.value = undefined
      detailError.value = '记录详情暂时无法加载，请重试。'
    }
  } finally {
    if (request === detailRevision) detailBusy.value = false
  }
}

async function selectRecord(id: string) {
  if (id === selectedId.value) return
  selectedId.value = id
  detail.value = undefined
  publishError.value = ''
  void fetchDetail(id)
  await nextTick()
  if (window.matchMedia('(max-width: 760px)').matches) {
    previewPanel.value?.focus()
  }
}

function applySearch() {
  keyword.value = search.value.trim()
  page.value = 1
}
function publishErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    switch (error.httpStatus) {
      case 409:
        return `该${objectLabel.value}已经发布，请核对最新发布状态。`
      case 403:
        return `当前账号没有权限发布该${objectLabel.value}。`
      case 422:
        return '发布资料校验失败，请重新选择记录后再试。'
      case 503:
        return '发布服务暂时不可用，请稍后重试。'
      case undefined:
        return '无法连接发布服务，请检查网络后重试。'
    }
  }
  return '发布请求失败，请稍后重试。'
}
function refreshCatalog(side: Perspective) {
  void loadCatalogObjects(side, { force: true }).catch(() => {
    // The next recommendation load retries a failed cache refresh.
  })
}

async function publish() {
  const record = detail.value
  const user = auth.user
  if (publishBusy.value || !record || !user || publicationState(record) !== 'available') return
  const objectId = recordId(record)
  const side = view.value
  publishBusy.value = true
  publishError.value = ''
  try {
    const { data } = await (side === 'research'
      ? api.publishAchievement({ achievement_id: objectId, updates: {} })
      : api.publishDemand({ demand_id: objectId, updates: {} }))
    if (auth.user?.user_id !== user.user_id) return
    refreshCatalog(side)
    if (!active) return
    if (selectedId.value === objectId) {
      detail.value = { ...record, publisher_user_id: user.user_id }
    }
    runs.value.unshift({ id: data.run_id, objectId, view: side, title: recordTitle(record) })
    void fetchList()
    await nextTick()
    trackersPanel.value?.scrollIntoView({ block: 'nearest' })
  } catch (error) {
    if (!active) return
    if (selectedId.value === objectId) publishError.value = publishErrorMessage(error)
    if (error instanceof ApiError && error.httpStatus === 409) {
      void fetchList()
      if (selectedId.value === objectId) void fetchDetail(objectId)
    }
  } finally {
    publishBusy.value = false
  }
}

watch(
  [publicationFilter, field],
  () => {
    page.value = 1
  },
  { flush: 'sync' },
)
watch([allowed, view, publicationFilter, field, keyword, page], fetchList, { immediate: true })
watch(
  allowed,
  (canPublish) => {
    if (canPublish && !taxonomy.value) void fetchTaxonomy()
  },
  { immediate: true },
)
onScopeDispose(() => {
  active = false
  listRevision++
  detailRevision++
})
</script>

<template>
  <section v-if="!allowed" class="tool-panel publish-access" aria-labelledby="publish-access-title">
    <h1 id="publish-access-title">当前账号无法访问此发布页面</h1>
    <el-alert
      :title="research ? '科研账号可发布科研成果。' : '企业账号可发布企业需求。'"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-button tag="router-link" type="primary" :to="ownRoute">{{ mineLabel }}</el-button>
  </section>
  <div v-else class="publish-page">
    <header class="publish-heading">
      <h1>{{ heading }}</h1>
      <p>从数据池选择已有记录并确认发布，提交后将自动触发匹配计算。</p>
    </header>

    <div class="publish-layout">
      <section class="tool-panel pool-panel" aria-labelledby="pool-title">
        <h2 id="pool-title">{{ research ? '科研成果池' : '企业需求池' }}</h2>
        <el-radio-group v-model="publicationFilter" aria-label="发布状态">
          <el-radio-button v-for="option in filters" :key="option.value" :value="option.value">
            {{ option.label }}
          </el-radio-button>
        </el-radio-group>
        <el-select
          v-model="field"
          aria-label="技术领域"
          :disabled="!taxonomy"
          :empty-values="[null, undefined]"
        >
          <el-option label="全部技术领域" value="" />
          <el-option
            v-for="option in fields"
            :key="option.code"
            :value="option.code"
            :label="option.label"
          />
        </el-select>
        <div v-if="taxonomyError" class="pool-feedback" role="status">
          <p>{{ taxonomyError }}</p>
          <el-button size="small" @click="fetchTaxonomy">重试加载标签</el-button>
        </div>
        <el-form v-if="research" class="pool-search" @submit.prevent="applySearch">
          <el-input
            v-model="search"
            aria-label="成果关键词"
            placeholder="搜索成果关键词"
            clearable
            @clear="applySearch"
          />
          <el-button native-type="submit">搜索</el-button>
        </el-form>

        <div v-if="listBusy" class="pool-feedback" role="status">正在读取数据池…</div>
        <div v-else-if="listError" class="pool-feedback" role="status">
          <p>{{ listError }}</p>
          <el-button size="small" @click="fetchList">重新加载</el-button>
        </div>
        <p v-else-if="!rows.length" class="pool-feedback" role="status">暂无符合筛选条件的记录。</p>
        <ul v-else class="pool-list">
          <li v-for="record in rows" :key="recordId(record)">
            <el-button
              class="pool-record"
              :aria-pressed="selectedId === recordId(record)"
              @click="selectRecord(recordId(record))"
            >
              <span class="record-content">
                <span class="record-title">{{ recordTitle(record) }}</span>
                <span class="record-meta">
                  <span>{{
                    primaryField(record) ? label('tech_field', primaryField(record)) : '待确认'
                  }}</span>
                  <span>{{ recordTrl(record) }}</span>
                  <el-tag
                    :type="publicationLabels[publicationState(record)].type"
                    size="small"
                    effect="plain"
                    disable-transitions
                  >
                    {{ publicationLabels[publicationState(record)].text }}
                  </el-tag>
                  <el-tag
                    v-if="recordId(record) === demoId"
                    size="small"
                    effect="plain"
                    disable-transitions
                  >
                    演示推荐
                  </el-tag>
                </span>
              </span>
            </el-button>
          </li>
        </ul>
        <el-pagination
          v-if="total > pageSize"
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          :pager-count="5"
          :disabled="listBusy"
          size="small"
          layout="prev, pager, next"
        />
      </section>

      <div class="publish-detail">
        <section
          ref="previewPanel"
          class="tool-panel preview-panel"
          tabindex="-1"
          aria-labelledby="preview-title"
        >
          <h2 id="preview-title">{{ research ? '成果发布预览' : '需求发布预览' }}</h2>
          <p v-if="!selectedId" class="preview-note">从数据池选择一条记录，查看预填资料。</p>
          <p v-else-if="detailBusy" class="preview-note" role="status">正在读取预填资料…</p>
          <div v-else-if="detailError" class="preview-note" role="status">
            <p>{{ detailError }}</p>
            <el-button @click="fetchDetail(selectedId)">重新读取资料</el-button>
          </div>

          <template v-if="!detailBusy && detail">
            <h3 class="preview-title">{{ recordTitle(detail) }}</h3>
            <template v-if="achievement">
              <div class="preview-text">
                <h4>中文能力画像 <span>系统生成，以原文为准</span></h4>
                <p>{{ achievement.capability_profile_zh || '暂无中文能力画像' }}</p>
              </div>
              <dl class="preview-fields">
                <div>
                  <dt>技术领域</dt>
                  <dd>
                    {{
                      labels(
                        'tech_field',
                        achievement.tech_fields.map(({ code }) => code),
                      )
                    }}
                  </dd>
                </div>
                <div>
                  <dt>应用场景</dt>
                  <dd>{{ labels('application_scenario', achievement.application_scenarios) }}</dd>
                </div>
                <div>
                  <dt>技术成熟度</dt>
                  <dd>{{ recordTrl(achievement) }}</dd>
                </div>
                <div>
                  <dt>审核状态</dt>
                  <dd>
                    <el-tag
                      v-if="achievement.review_status === 'needs_review'"
                      type="warning"
                      size="small"
                      effect="plain"
                      disable-transitions
                      >待复核</el-tag
                    >
                    <template v-else>{{
                      reviewLabels[achievement.review_status] ?? '待确认'
                    }}</template>
                  </dd>
                </div>
                <div>
                  <dt>知识产权状态</dt>
                  <dd>
                    {{ achievement.ip_status ? label('ip_status', achievement.ip_status) : '未知' }}
                  </dd>
                </div>
                <div>
                  <dt>发表年份</dt>
                  <dd>{{ achievement.publication_year }}</dd>
                </div>
                <div>
                  <dt>来源</dt>
                  <dd>
                    <el-link
                      v-if="source"
                      :href="source"
                      type="primary"
                      target="_blank"
                      rel="noopener noreferrer"
                      >查看原文来源</el-link
                    ><span v-else>待确认</span>
                  </dd>
                </div>
              </dl>
            </template>

            <template v-if="demand">
              <p class="preview-enterprise">
                {{ demand.enterprise.display_name }}
                <el-tag type="info" size="small" effect="plain" disable-transitions
                  >模拟资料</el-tag
                >
              </p>
              <div class="preview-text">
                <h4>技术痛点</h4>
                <p>{{ demand.pain_point }}</p>
              </div>
              <div class="preview-text">
                <h4>期望方案</h4>
                <p>{{ demand.expected_solution }}</p>
              </div>
              <dl class="preview-fields">
                <div>
                  <dt>最低成熟度要求</dt>
                  <dd>{{ recordTrl(demand) }}</dd>
                </div>
                <div>
                  <dt>技术领域</dt>
                  <dd>{{ labels('tech_field', demand.tech_fields) }}</dd>
                </div>
                <div>
                  <dt>应用场景</dt>
                  <dd>{{ labels('application_scenario', demand.application_scenarios) }}</dd>
                </div>
                <div>
                  <dt>合作方式</dt>
                  <dd>{{ labels('cooperation_mode', demand.cooperation_modes) }}</dd>
                </div>
                <div>
                  <dt>地区</dt>
                  <dd>{{ label('region', demand.region) }}</dd>
                </div>
                <div>
                  <dt>预算</dt>
                  <dd>{{ demand.budget_range || '待确认' }}</dd>
                </div>
                <div>
                  <dt>周期</dt>
                  <dd>{{ demand.timeline || '待确认' }}</dd>
                </div>
              </dl>
              <div class="preview-text">
                <h4>技术指标</h4>
                <ul v-if="demand.technical_metrics.length" class="preview-metrics">
                  <li v-for="(metric, index) in demand.technical_metrics" :key="index">
                    <span>{{ metric.name }}</span>
                    <strong>{{ metric.value }} {{ metric.unit }}</strong>
                  </li>
                </ul>
                <p v-else class="preview-note">待确认</p>
              </div>
            </template>
          </template>

          <div
            v-if="publishError || (!detailBusy && detail && !selectedRun)"
            class="publish-actions"
          >
            <el-alert
              v-if="publishError"
              :title="publishError"
              type="error"
              :closable="false"
              show-icon
            />
            <template v-if="!detailBusy && detail && !selectedRun">
              <el-button
                v-if="publicationState(detail) === 'available'"
                type="primary"
                :loading="publishBusy"
                @click="publish"
              >
                确认发布并触发匹配
              </el-button>
              <el-button
                v-else-if="publicationState(detail) === 'mine'"
                tag="router-link"
                type="primary"
                :to="recommendations(selectedId)"
              >
                前往查看推荐结果
              </el-button>
              <template v-else>
                <el-alert title="该记录已被其他账号认领" type="info" :closable="false" show-icon />
                <el-button disabled>确认发布并触发匹配</el-button>
              </template>
            </template>
          </div>
        </section>

        <div v-if="runs.length" ref="trackersPanel" class="run-list">
          <PipelineRunTracker
            v-for="run in runs"
            :key="run.id"
            :run-id="run.id"
            :object-id="run.objectId"
            :title="run.title"
            @finished="refreshCatalog(run.view)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.publish-page {
  padding-bottom: 28px;
}
.publish-heading {
  margin-bottom: 20px;
}
.publish-heading p {
  margin-top: 6px;
  color: var(--muted);
}
.publish-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: 22px;
  align-items: start;
}
.pool-panel,
.publish-detail,
.preview-panel,
.run-list,
.publish-access {
  display: grid;
  gap: 14px;
  min-width: 0;
}
.publish-access {
  max-width: 660px;
}
.pool-search {
  display: flex;
  gap: 8px;
}
.pool-search .el-input {
  min-width: 0;
}
.pool-feedback,
.preview-note {
  color: var(--muted);
}
.pool-feedback .el-button,
.preview-note .el-button {
  margin-top: 8px;
}
.pool-list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pool-record.el-button {
  width: 100%;
  height: auto;
  justify-content: flex-start;
  padding: 10px 12px;
  white-space: normal;
  text-align: left;
  line-height: 1.5;
}
.pool-record[aria-pressed='true'] {
  background: var(--el-color-primary-light-9);
  border-color: var(--accent);
}
.record-content {
  display: grid;
  min-width: 0;
  gap: 5px;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.record-title {
  font-weight: 600;
}
.record-meta,
.preview-enterprise {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 10px;
}
.record-meta {
  color: var(--muted);
  font-size: 12px;
}
.preview-panel {
  overflow-wrap: anywhere;
}
.preview-title {
  font-size: 18px;
}
.preview-text h4 {
  margin-bottom: 4px;
}
.preview-text h4 span {
  margin-left: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}
.preview-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  padding-block: 12px;
  border-block: 1px solid var(--line);
}
.preview-fields dt {
  font-size: 13px;
  color: var(--muted);
}
.preview-fields dd {
  margin: 2px 0 0;
}
.preview-metrics {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}
.preview-metrics li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--line);
}
.preview-metrics strong {
  flex-shrink: 0;
  max-width: 55%;
}
.publish-actions {
  display: grid;
  justify-items: start;
  gap: 10px;
  padding-top: 6px;
}
.publish-access .el-button {
  justify-self: start;
}
@media (max-width: 760px) {
  .publish-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
}
</style>
