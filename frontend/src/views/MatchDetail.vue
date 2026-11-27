<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, apiMode } from '../api'
import { auth } from '../auth'
import { loadTaxonomy, label, labels, safeSource } from '../catalog'
import type { Achievement, Demand, Match, RiskDimension } from '../types'
import Score from '../components/Score.vue'
import Icon from '../components/Icon.vue'
import RiskRadar from '../components/RiskRadar.vue'
import IntentPanel from '../components/IntentPanel.vue'
import { formatMetricMatched, formatMetricValue, formatSnippetSource } from '../utils/display'
import { recommendationsRoute } from '../utils/recommendationsRoute'
const route = useRoute()
const backToRecommendations = computed(() =>
  recommendationsRoute(auth.user?.role ?? 'enterprise', route.query),
)
const isMock = apiMode === 'mock'
const busy = ref(true),
  error = ref('')
const match = ref<Match | null>(null),
  achievement = ref<Achievement | null>(null),
  demand = ref<Demand | null>(null)
const dimensions: { key: RiskDimension; name: string }[] = [
  { key: 'technical', name: '技术风险' },
  { key: 'market', name: '市场风险' },
  { key: 'ip', name: '知识产权风险' },
  { key: 'collaboration', name: '合作风险' },
]
const usableRisk = computed(() => (!match.value?.is_stale ? match.value?.risk : null))
const usableEvidence = computed(() => {
  const evidence = match.value?.evidence
  if (match.value?.is_stale || !evidence) return null
  return evidence.snippets?.length ||
    evidence.metric_matches?.length ||
    evidence.tag_matches?.length
    ? evidence
    : null
})
let revision = 0
async function load() {
  const request = ++revision
  busy.value = true
  error.value = ''
  match.value = null
  try {
    const [m] = await Promise.all([api.getMatch(String(route.params.id || '')), loadTaxonomy()])
    if (request !== revision) return
    const [a, d] = await Promise.all([
      api.getAchievement(m.data.achievement_summary.achievement_id),
      api.getDemand(m.data.demand_summary.demand_id),
    ])
    if (request !== revision) return
    match.value = m.data
    achievement.value = a.data
    demand.value = d.data
  } catch (e) {
    if (request === revision) error.value = e instanceof Error ? e.message : '暂时无法加载详情'
  } finally {
    if (request === revision) busy.value = false
  }
}
watch(() => route.params.id, load, { immediate: true })
</script>
<template>
  <div v-if="busy" class="loading-state" role="status">正在读取匹配详情…</div>
  <div v-else-if="error" class="empty-state" role="alert">
    <h1>无法显示匹配详情</h1>
    <p>{{ error }}</p>
    <RouterLink class="primary-button" :to="backToRecommendations">返回推荐列表</RouterLink>
  </div>
  <article v-else-if="match && achievement && demand" class="detail-page">
    <header class="detail-heading">
      <div>
        <h1>匹配详情</h1>
        <p>这一条科研成果，与这一条企业需求。</p>
        <span v-if="match.is_stale" class="stale-notice"
          >配对已失效，推荐理由、风险和证据待重算</span
        >
      </div>
      <Score :value="match.total_score" large :stale="match.is_stale" />
    </header>
    <div class="comparison-grid">
      <section class="comparison-column" aria-labelledby="achievement-heading">
        <div class="section-label">
          <h2 id="achievement-heading">科研成果</h2>
          <span class="data-label">真实论文</span>
          <el-tag
            v-if="auth.isResearcher && achievement.publisher_user_id === auth.user?.user_id"
            effect="plain"
            size="small"
            disable-transitions
            >我已发布</el-tag
          >
          <el-tag
            v-if="achievement.review_status === 'needs_review'"
            type="warning"
            effect="light"
            size="small"
            disable-transitions
            >待审核/待复核</el-tag
          >
        </div>
        <h3 class="object-title">{{ achievement.title_original }}</h3>
        <p v-if="achievement.capability_profile_zh">{{ achievement.capability_profile_zh }}</p>
        <p v-if="achievement.capability_profile_zh" class="small-note">
          中文简介由系统生成，以原文为准。
        </p>
        <dl class="facts-grid">
          <div>
            <dt>技术方向</dt>
            <dd>
              {{
                labels(
                  'tech_field',
                  achievement.tech_fields.map((t) => t.code),
                )
              }}
            </dd>
          </div>
          <div>
            <dt>技术成熟度</dt>
            <dd>{{ label('trl', achievement.trl) }}</dd>
          </div>
          <div>
            <dt>知识产权</dt>
            <dd>
              {{
                achievement.ip_status ? label('ip_status', achievement.ip_status) : '待确认/未知'
              }}
            </dd>
          </div>
          <div>
            <dt>发表年份</dt>
            <dd>{{ achievement.publication_year }}</dd>
          </div>
          <div>
            <dt>成果类型</dt>
            <dd>{{ label('type', achievement.type) }}</dd>
          </div>
          <div>
            <dt>应用场景</dt>
            <dd>{{ labels('application_scenario', achievement.application_scenarios) }}</dd>
          </div>
        </dl>
        <details class="source-disclosure">
          <summary>查看原文摘要与来源</summary>
          <p class="abstract-text">{{ achievement.abstract_original || '尚无摘要' }}</p>
          <p v-if="isMock" class="small-note">如需完整论文内容，请查看原始来源。</p>
          <a
            v-if="safeSource(achievement.source_url)"
            :href="safeSource(achievement.source_url)"
            target="_blank"
            rel="noopener noreferrer"
            class="source-link"
            >查看原始来源<Icon name="external"
          /></a>
          <p v-else class="small-note">尚无可访问的来源链接。</p>
        </details>
      </section>
      <section class="comparison-column" aria-labelledby="demand-heading">
        <div class="section-label">
          <h2 id="demand-heading">企业需求</h2>
          <span class="data-label">模拟资料</span>
          <el-tag
            v-if="auth.isEnterprise && demand.publisher_user_id === auth.user?.user_id"
            effect="plain"
            size="small"
            disable-transitions
            >我已发布</el-tag
          >
        </div>
        <h3 class="object-title">{{ demand.title }}</h3>
        <p>{{ demand.pain_point }}</p>
        <dl class="facts-grid">
          <div>
            <dt>企业化名</dt>
            <dd>{{ demand.enterprise.display_name }}</dd>
          </div>
          <div>
            <dt>成熟度要求</dt>
            <dd>{{ label('trl', demand.required_trl) }}</dd>
          </div>
          <div>
            <dt>合作方式</dt>
            <dd>{{ labels('cooperation_mode', demand.cooperation_modes) }}</dd>
          </div>
          <div>
            <dt>意向地区</dt>
            <dd>{{ label('region', demand.region) }}</dd>
          </div>
          <div>
            <dt>预算范围</dt>
            <dd>{{ demand.budget_range || '尚未提供' }}</dd>
          </div>
          <div>
            <dt>预计周期</dt>
            <dd>{{ demand.timeline || '尚未提供' }}</dd>
          </div>
        </dl>
        <div class="expected-solution">
          <h4>期望方案</h4>
          <p>{{ demand.expected_solution }}</p>
        </div>
        <details class="source-disclosure">
          <summary>查看其他需求资料</summary>
          <dl class="context-facts">
            <div>
              <dt>行业与规模</dt>
              <dd>
                {{ label('industry', demand.enterprise.industry) }}、{{
                  label('enterprise_size', demand.enterprise.size)
                }}
              </dd>
            </div>
            <div>
              <dt>应用场景</dt>
              <dd>{{ labels('application_scenario', demand.application_scenarios) }}</dd>
            </div>
            <div>
              <dt>知识产权要求</dt>
              <dd>{{ demand.ip_requirement || '尚未提供' }}</dd>
            </div>
            <div>
              <dt>有效期</dt>
              <dd>{{ demand.valid_until }}（{{ label('status', demand.status) }}）</dd>
            </div>
          </dl>
          <p class="small-note">{{ demand.source_note }}</p>
        </details>
      </section>
    </div>
    <IntentPanel :achievement="achievement" :demand="demand" :match-id="match.match_id" />
    <section class="detail-section" aria-labelledby="reason-heading">
      <div class="section-label">
        <h2 id="reason-heading">为什么推荐</h2>
      </div>
      <p class="detail-reason">
        {{ match.is_stale ? '当前配对已失效，需重新计算推荐理由。' : match.reason }}
      </p>
      <template v-if="usableEvidence">
        <div class="evidence-grid">
          <blockquote
            v-for="(snippet, idx) in usableEvidence.snippets"
            :key="snippet.source_ref + '-' + idx"
          >
            <span class="quote-label">{{
              snippet.side === 'achievement' ? '成果原文' : '需求原文'
            }}</span>
            <p>{{ snippet.text }}</p>
            <cite>{{ formatSnippetSource(snippet) }}</cite>
          </blockquote>
        </div>
        <h3 class="subheading">技术指标对照</h3>
        <div class="table-scroll" tabindex="0" role="region" aria-label="技术指标对照表">
          <table>
            <thead>
              <tr>
                <th scope="col">指标</th>
                <th scope="col">企业要求</th>
                <th scope="col">成果资料</th>
                <th scope="col">核查状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="metric in usableEvidence.metric_matches" :key="metric.name">
                <th scope="row">{{ metric.name }}</th>
                <td>{{ formatMetricValue(metric.required_value, metric.unit, '未指定') }}</td>
                <td>
                  {{ formatMetricValue(metric.achievement_value, metric.unit, '尚无核查数据') }}
                </td>
                <td>{{ formatMetricMatched(metric.matched) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!usableEvidence.metric_matches?.length" class="small-note">尚无指标对照资料。</p>
      </template>
      <div v-else class="pending-analysis">
        <Icon name="info" />
        <div>
          <strong>{{ match.is_stale ? '匹配证据待重算' : '暂无精排证据' }}</strong>
          <p>
            {{
              match.is_stale
                ? '当前配对已失效，需重新计算匹配证据。'
                : '精排完成后将在此展示原文摘录与指标对照。'
            }}
          </p>
        </div>
      </div>
    </section>
    <section class="detail-section" aria-labelledby="risk-heading">
      <div class="section-label">
        <h2 id="risk-heading">四项风险</h2>
      </div>
      <div v-if="usableRisk" class="risk-layout">
        <RiskRadar :risk="usableRisk" />
        <dl class="risk-details">
          <div v-for="dimension in dimensions" :key="dimension.key">
            <dt>
              {{ dimension.name }}<span>{{ usableRisk[dimension.key].score }} / 5</span>
            </dt>
            <dd>{{ usableRisk[dimension.key].description }}</dd>
          </div>
        </dl>
      </div>
      <div v-else class="pending-analysis">
        <Icon name="info" />
        <div>
          <strong>{{ match.is_stale ? '风险待重算' : '风险待精排/评估' }}</strong>
          <p>
            {{
              match.is_stale
                ? '当前配对已失效，需重新评估四维风险。'
                : '精排完成后将在此展示四维风险评估。'
            }}
          </p>
        </div>
      </div>
    </section>
    <section class="detail-section mitigation-section" aria-labelledby="mitigation-heading">
      <h2 id="mitigation-heading">综合提醒与规避建议</h2>
      <template v-if="usableRisk"
        ><p>{{ usableRisk.overall.summary }}</p>
        <ul>
          <li v-for="item in usableRisk.overall.mitigation" :key="item">{{ item }}</li>
        </ul></template
      >
      <p v-else>
        {{
          match.is_stale
            ? '当前配对已失效，重新计算后将更新综合建议。'
            : '精排完成后将在此展示综合提醒与规避建议。'
        }}
      </p>
    </section>
    <details class="version-disclosure">
      <summary>资料来源与版本</summary>
      <dl class="context-facts">
        <div>
          <dt>数据版本</dt>
          <dd>{{ match.dataset_version }}</dd>
        </div>
        <div>
          <dt>标签版本</dt>
          <dd>{{ match.taxonomy_version }}</dd>
        </div>
        <div v-if="isMock">
          <dt>数据来源</dt>
          <dd>本地模拟数据</dd>
        </div>
        <template v-else>
          <div>
            <dt>匹配模型</dt>
            <dd>{{ match.model || '未记录' }}</dd>
          </div>
          <div>
            <dt>提示词版本</dt>
            <dd>{{ match.prompt_version || '未记录' }}</dd>
          </div>
          <div>
            <dt>向量模型版本</dt>
            <dd>{{ match.embedding_model_version || '未记录' }}</dd>
          </div>
        </template>
      </dl>
      <p class="small-note">匹配记录：{{ match.match_id }}</p>
    </details>
  </article>
</template>
