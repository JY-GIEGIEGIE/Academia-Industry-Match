import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { parseArgs } from 'node:util'
import { URL } from 'node:url'

const { values } = parseArgs({
  options: { source: { type: 'string' }, help: { type: 'boolean', short: 'h' } },
  allowPositionals: false,
})
const usage =
  'Usage: node <path-to-build-mock-data.mjs> --source "<handoff-directory>"\n' +
  'The source directory must contain data/processed/*.jsonl.\n' +
  'Outputs are written beside this script, regardless of the current working directory.\n' +
  'The checked-in fixtures are sufficient to run the demo; regeneration is optional.'
if (values.help) {
  console.log(usage)
  process.exit(0)
}
if (!values.source) {
  console.error('Missing --source.\n' + usage)
  process.exit(1)
}
const source = resolve(values.source)
const load = (name) =>
  readFileSync(resolve(source, 'data/processed', name), 'utf8')
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter(Boolean)
    .map(JSON.parse)
const allAchievements = load('achievements_clean_v0.1.jsonl')
const allDemands = load('demands_v0.1.jsonl')
const enterprises = load('enterprises_v0.1.jsonl')
const profiles = [
  '这篇论文讨论固态电解质在固态锂离子电池中的应用，聚焦相关技术路线与材料体系。',
  '这篇论文研究锂银锗矿型硫化物电解质，关注离子电导率与空气稳定性，与固态电解质研发需求高度相关。',
  '这篇论文关注锂银锗矿固态电解质中的碘占位及其结构优化，面向全固态锂金属电池应用。',
  '这篇综述系统梳理了固态锂离子电池电解质的离子电导率与离子传输机制，适合用于技术路线比对。',
]
const clip = (text, max) => (text && text.length > max ? text.slice(0, max - 1) + '…' : text)
const achievementIds = [
  'ach_openalex_W7127158161',
  'ach_openalex_W4200428349',
  'ach_openalex_W4413607194',
  'ach_openalex_W4293238043',
]
const selected = achievementIds.map((id) => {
  const record = allAchievements.find((a) => a.achievement_id === id)
  if (!record || record.query_tag !== 'electrolyte' || record.dataset_version !== 'v0.1') {
    throw new Error('Expected original v0.1 electrolyte record: ' + id)
  }
  return record
})
const achievements = selected.map((a, i) => ({
  achievement_id: a.achievement_id,
  title_original: a.title_original,
  abstract_preview: clip(a.abstract_original || null, 300),
  capability_profile_zh: profiles[i],
  publication_year: a.publication_year,
  type: a.type,
  source: a.source,
  source_url: a.source_url,
  language: a.language,
  trl: null,
  tech_fields: [{ code: 'electrolyte', is_primary: true }],
  application_scenarios: [],
  is_simulated: false,
  dataset_version: a.dataset_version,
  doi: a.doi || null,
  abstract_original: clip(a.abstract_original || '', 600),
  venue: a.venue || null,
  keywords: a.keywords || [],
  topics: a.topics || [],
  clean_status: a.clean_status,
  review_status: 'pending',
  trl_evidence: null,
  key_metrics: [],
  material_system: null,
  process: [],
  ip_status: 'unknown',
}))
const keys = [
  'demand_id',
  'enterprise_id',
  'title',
  'pain_point',
  'expected_solution',
  'technical_metrics',
  'budget_range',
  'timeline',
  'cooperation_modes',
  'required_trl',
  'tech_fields',
  'application_scenarios',
  'ip_requirement',
  'region',
  'status',
  'valid_until',
  'is_simulated',
  'source_note',
  'dataset_version',
]
const demands = allDemands
  .filter((d) => d.tech_fields.includes('electrolyte'))
  .slice(0, 5)
  .map((d) => {
    const e = enterprises.find((e) => e.enterprise_id === d.enterprise_id)
    if (!e || !e.is_simulated || !d.is_simulated)
      throw new Error('Expected simulated enterprise/demand')
    return {
      ...Object.fromEntries(keys.map((k) => [k, d[k] ?? null])),
      enterprise: { display_name: e.display_name, industry: e.industry, size: e.size },
    }
  })
const dims = (dimension, label, applies_to, entries, type = 'enum') => ({
  dimension,
  label,
  type,
  applies_to,
  values: entries.map(([code, label]) => ({ code: String(code), label })),
})
const taxonomy = {
  taxonomy_version: 'v0.1',
  dimensions: [
    dims(
      'tech_field',
      '技术领域',
      ['achievement', 'demand'],
      [
        ['cathode_material', '正极材料'],
        ['anode_material', '负极材料'],
        ['electrolyte', '电解质'],
        ['separator', '隔膜'],
        ['cell_system', '电芯与系统'],
        ['recycling', '回收与梯次利用'],
        ['flow_battery', '液流电池'],
        ['supercapacitor', '超级电容器'],
      ],
    ),
    dims(
      'application_scenario',
      '应用场景',
      ['achievement', 'demand'],
      [
        ['ev_power', '动力电池'],
        ['grid_storage', '电网储能'],
        ['cni_storage', '工商业储能'],
        ['residential_storage', '户用储能'],
        ['consumer_electronics', '消费电子'],
        ['e_tool_two_wheeler', '电动工具/两轮车'],
        ['special', '特种应用'],
        ['recycling_industry', '回收产业'],
      ],
    ),
    dims(
      'cooperation_mode',
      '合作模式',
      ['achievement', 'demand'],
      [
        ['transfer', '技术转让'],
        ['license', '技术许可'],
        ['joint_rd', '联合研发'],
        ['joint_lab', '共建实验室'],
        ['tech_service', '技术服务/咨询'],
      ],
    ),
    dims(
      'ip_status',
      '知识产权状态',
      ['achievement'],
      [
        ['granted', '已授权'],
        ['pending', '申请中'],
        ['published', '已公开'],
        ['unknown', '未知'],
      ],
    ),
    dims(
      'region',
      '意向地区',
      ['demand', 'enterprise'],
      [
        ['yangtze_delta', '长三角'],
        ['pearl_river_delta', '珠三角'],
        ['beijing_tianjin_hebei', '京津冀'],
        ['chengdu_chongqing', '成渝'],
        ['other', '其他'],
        ['any', '不限'],
      ],
    ),
    dims(
      'industry',
      '企业行业',
      ['demand', 'enterprise'],
      [
        ['battery_manufacturing', '电池制造'],
        ['material_manufacturing', '材料制造'],
        ['ev_oem', '整车'],
        ['ess_integrator', '储能系统'],
        ['recycling', '回收'],
        ['other', '其他'],
      ],
    ),
    dims(
      'enterprise_size',
      '企业规模',
      ['enterprise', 'demand'],
      [
        ['large', '大型'],
        ['medium', '中型'],
        ['small', '小型'],
      ],
    ),
    dims(
      'status',
      '需求状态',
      ['demand'],
      [
        ['draft', '草稿'],
        ['active', '生效'],
        ['expired', '已过期'],
        ['closed', '已关闭'],
      ],
    ),
    dims(
      'language',
      '语言',
      ['achievement'],
      [
        ['en', '英文'],
        ['zh', '中文'],
        ['mixed', '中英混合'],
        ['unknown', '未知'],
      ],
    ),
    dims(
      'type',
      '成果类型',
      ['achievement'],
      [
        ['article', '期刊论文'],
        ['review', '综述'],
        ['preprint', '预印本'],
        ['patent', '专利'],
        ['other', '其他'],
      ],
    ),
    dims(
      'trl',
      '技术成熟度',
      ['achievement', 'demand'],
      [
        [1, '1 基本原理'],
        [2, '2 技术概念'],
        [3, '3 实验室验证'],
        [4, '4 实验室器件'],
        [5, '5 相关环境验证/中试'],
        [6, '6 原型演示'],
        [7, '7 实际环境演示'],
        [8, '8 系统定型'],
        [9, '9 商业运行'],
      ],
      'ordinal',
    ),
  ],
}
const matches = demands.flatMap((d, di) =>
  achievements.map((a, ai) => {
    const n = di * 4 + ai,
      stale = n >= 17,
      pending = n === 3,
      scores = [92, 86, 77, 65],
      overall = [3, 4, 2, 5][(di + ai) % 4]
    const angle = [
      '技术路线概览',
      '硫化物电解质的导电与稳定性',
      '电解质组成与界面相关研究',
      '离子传输机制综述',
    ][ai]
    return {
      match_id: 'mock_match_' + String(n + 1).padStart(3, '0'),
      achievement_id: a.achievement_id,
      demand_id: d.demand_id,
      total_score: scores[ai] - di * 2,
      tag_score: 80 - ai * 4,
      semantic_score: 85 - di * 3 - ai,
      llm_score: pending || stale ? null : scores[ai] - 5,
      risk_overall_score: pending || stale ? null : overall,
      reason:
        '该成果聚焦“' +
        angle +
        '”，与需求“' +
        d.title +
        '”技术方向契合，建议结合原文进一步核查关键性能指标与中试条件。',
      is_stale: stale,
      created_at: '2026-11-22T02:00:00Z',
      risk:
        pending || stale
          ? null
          : {
              technical: {
                score: 4,
                description:
                  '企业要求至少达到 TRL ' +
                  d.required_trl +
                  '，该成果成熟度尚待评估，需重点核查中试与工程放大条件。',
              },
              market: {
                score: 2 + (di % 2),
                description: '企业应用场景明确，需进一步确认该成果在目标场景下的适配度。',
              },
              ip: {
                score: 3,
                description: '知识产权状态尚未披露，合作前建议核查专利权属与许可范围。',
              },
              collaboration: {
                score: overall,
                description: '企业已明确合作方式偏好，建议进一步对接研发资源与合作条件。',
              },
              overall: {
                summary:
                  '技术方向具备进一步探讨价值，主要关注点在于关键性能指标核验、中试放大条件及知识产权归属。',
                mitigation: [
                  '对照原文核查关键指标及实验条件',
                  '核实技术成熟度与放大验证资料',
                  '确认知识产权、合作边界和投入条件',
                ],
              },
            },
      evidence:
        pending || stale
          ? null
          : {
              tag_matches: [],
              snippets: [
                {
                  side: 'achievement',
                  field: 'title_original',
                  text: clip(a.title_original, 200),
                  source_ref: 'achievement.title_original',
                },
                {
                  side: 'demand',
                  field: 'pain_point',
                  text: clip(d.pain_point, 200),
                  source_ref: 'demand.pain_point',
                },
              ],
              metric_matches: d.technical_metrics.map((m) => ({
                name: m.name,
                required_value: m.value,
                unit: m.unit,
              })),
            },
      model: 'mock-only-no-model-run',
      prompt_version: 'mock-manual-v1',
      dataset_version: 'v0.1',
      taxonomy_version: 'v0.1',
      embedding_model_version: 'mock-only-no-embedding',
    }
  }),
)
const json = JSON.stringify({ achievements, demands, matches, taxonomy }, null, 2) + '\n'
writeFileSync(new URL('./fixtures.json', import.meta.url), json)
const manifest = {
  sprint: '2026-11-22',
  dataset_version: 'v0.1',
  taxonomy_version: 'v0.1',
  embedding_model_version: 'mock-only-no-embedding',
  source: 'S-02 v0.1 processed data (local handoff)',
  source_counts: {
    achievements: allAchievements.length,
    demands: allDemands.length,
    enterprises: enterprises.length,
  },
  demo_counts: {
    achievements: achievements.length,
    demands: demands.length,
    matches: matches.length,
  },
  hash: createHash('sha256').update(json).digest('hex'),
  notes: [
    'Whitelist fields only; no authors, institutions, legal names, contacts or raw snapshots.',
    'Abstract excerpt <=600 characters; list preview <=300. Full abstracts stay outside this project.',
    'Electrolyte demo tags manually grounded in titles and collection category; not accepted pipeline labels.',
    'Chinese profiles prepared by Codex from titles for demo; not formal extraction output.',
    'Scores, reasons and risks are demo fixtures; no matching, embedding or reranking model was run.',
    'Four real achievements and five simulated demands form 20 unique pairs. One pending and three stale fixtures included.',
  ],
}
writeFileSync(new URL('./manifest.json', import.meta.url), JSON.stringify(manifest, null, 2) + '\n')
console.log(JSON.stringify({ counts: manifest.demo_counts, hash: manifest.hash }))
