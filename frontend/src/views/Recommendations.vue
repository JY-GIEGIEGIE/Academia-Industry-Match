<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalog, loadCatalogObjects, loadObject, loadTaxonomy, label, labels } from '../catalog'
import { api, ApiError, apiMode } from '../api'
import { auth } from '../auth'
import type { MatchSummary, Page, Perspective, Achievement, Demand } from '../types'
import Icon from '../components/Icon.vue'
import Score from '../components/Score.vue'
const route = useRoute(),
  router = useRouter()
const busy = ref(true),
  error = ref(''),
  mobileOpen = ref(false)
const emptyPage: Page<MatchSummary> = {
  items: [],
  pagination: { page: 1, page_size: 3, total: 0, total_pages: 0 },
}
const result = ref(emptyPage)
const isMock = apiMode === 'mock'
const current = ref<Achievement | Demand | null>(null)
const view = computed<Perspective>(() => (auth.isResearcher ? 'research' : 'enterprise'))
const objectLabel = computed(() => (auth.isResearcher ? '成果' : '需求'))
const targetLabel = computed(() => (auth.isResearcher ? '企业需求' : '科研成果'))
const options = computed(() => {
  const userId = auth.user?.user_id
  const objects =
    view.value === 'enterprise'
      ? catalog.demands.map((d) => ({
          id: d.demand_id,
          title: d.title,
          publisherId: d.publisher_user_id,
        }))
      : catalog.achievements.map((a) => ({
          id: a.achievement_id,
          title: a.title_original,
          publisherId: a.publisher_user_id,
        }))
  return objects
    .map(({ id, title, publisherId }) => {
      const mine = Boolean(userId && publisherId === userId)
      return { id, title: mine ? `[我已发布] ${title}` : title, mine }
    })
    .sort((a, b) => Number(b.mine) - Number(a.mine))
})
const myOption = computed(() => options.value.find((option) => option.mine))
const demoObjectId = computed(() =>
  view.value === 'enterprise' ? 'dem_005' : 'ach_openalex_W4200428349',
)
const objectId = computed(() =>
  String(
    route.query.object ||
      myOption.value?.id ||
      options.value.find((option) => option.id === demoObjectId.value)?.id ||
      options.value[0]?.id ||
      '',
  ),
)
const minScore = computed(() => Number(route.query.min_score || 0))
const stale = computed(() => route.query.is_stale === 'true')
const page = computed(() => Number(route.query.page || 1))
const currentDemand = computed(() =>
  current.value && 'demand_id' in current.value ? current.value : null,
)
const currentAchievement = computed(() =>
  current.value && 'achievement_id' in current.value ? current.value : null,
)
let revision = 0
function update(values: Record<string, string | number>) {
  router.replace({
    path: '/recommendations',
    query: {
      ...route.query,
      view: view.value,
      object: objectId.value,
      page: '1',
      ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, String(v)])),
    },
  })
}
function selectObject(event: Event) {
  update({ object: (event.target as HTMLSelectElement).value })
}
function selectScore(event: Event) {
  update({ min_score: (event.target as HTMLSelectElement).value })
}
function selectState(event: Event) {
  update({ is_stale: (event.target as HTMLSelectElement).value })
}
function reset() {
  update({ min_score: 0, is_stale: 'false' })
}
function riskLabel(match: MatchSummary) {
  if (match.is_stale) return '风险待重算'
  if (match.risk_overall_score == null) return isMock ? '风险待精排/评估' : '四维风险见详情'
  return `综合风险 ${match.risk_overall_score}/5`
}
function detailQuery() {
  return {
    ...route.query,
    view: view.value,
    object: objectId.value,
    min_score: String(minScore.value),
    is_stale: String(stale.value),
    page: String(page.value),
  }
}
async function load() {
  const request = ++revision
  if (!auth.isAuthenticated || route.path !== '/recommendations') return
  busy.value = true
  error.value = ''
  try {
    await Promise.all([loadCatalogObjects(view.value), loadTaxonomy()])
    if (request !== revision) return
    if (!objectId.value) {
      result.value = emptyPage
      current.value = null
      return
    }
    const [list, object] = await Promise.all([
      api.getMatches(view.value, objectId.value, {
        page: page.value,
        page_size: 3,
        min_score: minScore.value,
        is_stale: stale.value,
      }),
      loadObject(view.value, objectId.value),
    ])
    if (request !== revision) return
    if (list.data.pagination.total_pages && page.value > list.data.pagination.total_pages) {
      update({ page: list.data.pagination.total_pages })
      return
    }
    result.value = list.data
    current.value = object.data
  } catch (e) {
    if (request === revision) {
      error.value =
        e instanceof ApiError && e.httpStatus === 404
          ? `当前${objectLabel.value}已不可用，请重新选择${objectLabel.value}。`
          : `暂时无法加载推荐的${targetLabel.value}，请重试。`
      result.value = emptyPage
      current.value = null
    }
  } finally {
    if (request === revision) busy.value = false
  }
}
watch([() => route.fullPath, () => auth.user?.user_id], load, { immediate: true })
</script>
<template>
  <div class="recommendation-layout">
    <aside class="context-panel">
      <button
        class="mobile-context-toggle"
        :aria-expanded="mobileOpen"
        @click="mobileOpen = !mobileOpen"
      >
        当前资料与筛选<Icon name="chevron" />
      </button>
      <div class="context-content" :class="{ 'mobile-expanded': mobileOpen }">
        <h2>我的{{ objectLabel }}</h2>
        <p class="small-note context-intro">
          {{
            auth.isResearcher ? '切换成果，查看适配的企业需求。' : '切换需求，查看推荐的科研成果。'
          }}
        </p>
        <label class="field-label" for="object-select">当前{{ objectLabel }}</label>
        <select
          id="object-select"
          :class="{ 'truncate-title': view === 'research' }"
          :title="options.find((option) => option.id === objectId)?.title"
          :value="objectId"
          :disabled="!options.length"
          @change="selectObject"
        >
          <option v-for="option in options" :key="option.id" :value="option.id">
            {{ option.title }}
          </option>
        </select>
        <RouterLink v-if="!busy && !myOption" class="source-link" to="/publish">
          前往发布{{ objectLabel }}
        </RouterLink>
        <div v-if="currentDemand" class="context-summary">
          <span v-if="currentDemand.is_simulated" class="data-label">模拟需求</span>
          <h3>{{ currentDemand.title }}</h3>
          <p>{{ currentDemand.pain_point }}</p>
          <dl class="context-facts">
            <div>
              <dt>企业化名</dt>
              <dd>{{ currentDemand.enterprise.display_name }}</dd>
            </div>
            <div>
              <dt>应用场景</dt>
              <dd>{{ labels('application_scenario', currentDemand.application_scenarios) }}</dd>
            </div>
            <div>
              <dt>成熟度要求</dt>
              <dd>{{ label('trl', currentDemand.required_trl) }}</dd>
            </div>
            <div>
              <dt>合作方式</dt>
              <dd>{{ labels('cooperation_mode', currentDemand.cooperation_modes) }}</dd>
            </div>
          </dl>
        </div>
        <div v-else-if="currentAchievement" class="context-summary">
          <span class="data-label">真实论文</span>
          <el-tag
            v-if="currentAchievement.review_status === 'needs_review'"
            type="warning"
            effect="light"
            size="small"
            disable-transitions
            >待审核/待复核</el-tag
          >
          <h3>{{ currentAchievement.title_original }}</h3>
          <p>
            {{
              currentAchievement.capability_profile_zh ||
              currentAchievement.abstract_preview ||
              '尚无摘要'
            }}
          </p>
          <dl class="context-facts">
            <div>
              <dt>技术成熟度</dt>
              <dd>{{ label('trl', currentAchievement.trl) }}</dd>
            </div>
            <div>
              <dt>发表年份</dt>
              <dd>{{ currentAchievement.publication_year }}</dd>
            </div>
            <div>
              <dt>知识产权</dt>
              <dd>{{ label('ip_status', currentAchievement.ip_status) }}</dd>
            </div>
          </dl>
        </div>
        <div class="context-filter">
          <label class="field-label" for="state-select">结果状态</label>
          <select id="state-select" :value="String(stale)" @change="selectState">
            <option value="false">有效匹配</option>
            <option value="true">待重算</option>
          </select>
        </div>
      </div>
    </aside>
    <section class="recommendations" aria-labelledby="recommendation-title" :aria-busy="busy">
      <div class="list-heading">
        <div>
          <h1 id="recommendation-title">为你推荐</h1>
          <p>
            {{
              view === 'enterprise'
                ? '从研究成果中，寻找解决需求的技术思路。'
                : '从企业需求中，寻找技术应用的可能。'
            }}
          </p>
        </div>
      </div>
      <div class="list-toolbar">
        <span class="result-count" aria-live="polite">{{
          busy
            ? '正在加载推荐…'
            : '共 ' + result.pagination.total + ' 条' + (stale ? '待重算' : '推荐')
        }}</span>
        <div class="toolbar-filter">
          <label for="score-select">最低适配度</label
          ><select id="score-select" :value="minScore" @change="selectScore">
            <option value="0">不限</option>
            <option value="70">70 分</option>
            <option value="80">80 分</option>
            <option value="90">90 分</option>
            <option value="100">100 分</option>
          </select>
        </div>
      </div>
      <div v-if="error" class="empty-state" role="alert">
        <h2>无法显示推荐</h2>
        <p>{{ error }}</p>
        <RouterLink
          v-if="route.query.object"
          class="primary-button"
          :to="{ path: '/recommendations', query: { view } }"
          >回到推荐首页</RouterLink
        >
        <button v-else class="primary-button" @click="load">重试</button>
      </div>
      <div v-else-if="busy" class="loading-state" role="status">正在加载推荐…</div>
      <div v-else-if="!objectId" class="empty-state">
        <h2>暂无可用于匹配的{{ objectLabel }}</h2>
        <p>发布{{ objectLabel }}后，即可查看推荐的{{ targetLabel }}。</p>
        <RouterLink class="primary-button" to="/publish">前往发布{{ objectLabel }}</RouterLink>
      </div>
      <div v-else-if="!result.items.length" class="empty-state">
        <h2>没有符合条件的{{ targetLabel }}</h2>
        <p>试着降低最低适配度，或切换当前{{ objectLabel }}与结果状态。</p>
        <button class="primary-button" @click="reset">重置筛选</button>
      </div>
      <template v-else>
        <ol class="match-list">
          <li v-for="match in result.items" :key="match.match_id" class="match-row">
            <div class="match-content">
              <div class="match-meta">
                <span class="tech-label">{{
                  view === 'enterprise'
                    ? labels(
                        'tech_field',
                        match.achievement_summary.tech_fields.map((t) => t.code),
                      )
                    : labels('tech_field', match.demand_summary.tech_fields)
                }}</span><span>{{
                  view === 'enterprise'
                    ? match.achievement_summary.publication_year +
                      ' 年 · ' +
                      label('type', match.achievement_summary.type)
                    : match.demand_summary.enterprise.display_name
                }}</span
                ><span class="data-label">{{
                  view === 'enterprise' ? '真实论文' : '模拟需求'
                }}</span>
              </div>
              <h2>
                <RouterLink :to="{ path: '/matches/' + match.match_id, query: detailQuery() }">{{
                  view === 'enterprise'
                    ? match.achievement_summary.title_original
                    : match.demand_summary.title
                }}</RouterLink>
              </h2>
              <p class="match-description">
                {{
                  view === 'enterprise'
                    ? match.achievement_summary.capability_profile_zh ||
                      match.achievement_summary.abstract_preview ||
                      '尚无摘要'
                    : match.demand_summary.pain_point
                }}
              </p>
              <div class="match-reason">
                <span>推荐理由</span>
                <p>
                  {{ match.is_stale ? '该配对已失效，原推荐理由与分析需重新计算。' : match.reason }}
                </p>
              </div>
            </div>
            <div class="match-actions">
              <Score :value="match.total_score" :stale="match.is_stale" /><span
                class="risk-summary"
                :class="{
                  'risk-pending': match.is_stale || (isMock && match.risk_overall_score == null),
                  'risk-neutral': !isMock && !match.is_stale && match.risk_overall_score == null,
                }"
                >{{ riskLabel(match) }}</span
              ><RouterLink
                class="detail-link"
                :to="{ path: '/matches/' + match.match_id, query: detailQuery() }"
                >查看详情<Icon name="next"
              /></RouterLink>
            </div>
          </li>
        </ol>
        <nav class="pagination" aria-label="推荐分页">
          <span>第 {{ result.pagination.page }} / {{ result.pagination.total_pages }} 页</span>
          <div>
            <button class="page-button" :disabled="page <= 1" @click="update({ page: page - 1 })">
              <Icon name="back" />上一页</button
            ><button
              class="page-button"
              :disabled="page >= result.pagination.total_pages"
              @click="update({ page: page + 1 })"
            >
              下一页<Icon name="next" />
            </button>
          </div>
        </nav>
      </template>
    </section>
  </div>
</template>

<style scoped>
.risk-neutral {
  color: var(--muted);
}
</style>
