<script setup lang="ts">
import { computed } from 'vue'
import type { Risk, RiskDimension } from '../types'
const props = defineProps<{ risk: Risk }>()
const dimensions: { key: RiskDimension; label: string }[] = [
  { key: 'technical', label: '技术' },
  { key: 'market', label: '市场' },
  { key: 'ip', label: '知识产权' },
  { key: 'collaboration', label: '合作' },
]
function points(level: number) {
  const r = (80 * level) / 5
  return '130,' + (125 - r) + ' ' + (130 + r) + ',125 130,' + (125 + r) + ' ' + (130 - r) + ',125'
}
const polygon = computed(() => {
  const r = dimensions.map((d) => props.risk[d.key].score * 16)
  return (
    '130,' +
    (125 - r[0]) +
    ' ' +
    (130 + r[1]) +
    ',125 130,' +
    (125 + r[2]) +
    ' ' +
    (130 - r[3]) +
    ',125'
  )
})
</script>
<template>
  <figure class="radar">
    <svg viewBox="0 0 260 260" role="img" aria-labelledby="radar-title radar-description">
      <title id="radar-title">四维风险雷达图（演示）</title>
      <desc id="radar-description">
        {{
          dimensions.map((d) => d.label + '风险' + risk[d.key].score + '分').join('，')
        }}。1最低，5最高，面积越大风险越高。
      </desc>
      <polygon
        v-for="level in 5"
        :key="level"
        :points="points(level)"
        fill="none"
        stroke="#dde5ee"
      />
      <path d="M130 45v160M50 125h160" stroke="#dde5ee" />
      <polygon :points="polygon" fill="#b978291a" stroke="#a36524" stroke-width="2" />
      <text x="130" y="27" text-anchor="middle">技术</text>
      <text x="226" y="129" text-anchor="middle">市场</text>
      <text x="130" y="230" text-anchor="middle">知识产权</text>
      <text x="27" y="129" text-anchor="middle">合作</text>
      <text
        v-for="level in 5"
        :key="'scale' + level"
        x="122"
        :y="125 - level * 16 + 4"
        class="radar-scale"
      >
        {{ level }}
      </text>
    </svg>
    <figcaption>1 最低 / 5 最高 · 越高风险越大</figcaption>
  </figure>
</template>
