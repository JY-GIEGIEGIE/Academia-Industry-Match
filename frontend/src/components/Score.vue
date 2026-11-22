<script setup lang="ts">
defineProps<{ value: number; large?: boolean; stale?: boolean }>()
</script>
<template>
  <div class="score" :class="{ 'score-large': large, 'score-stale': stale }">
    <span class="score-label">{{ stale ? '历史适配度 · 演示' : '适配度 · 演示' }}</span>
    <div>
      <strong>{{ value }}</strong><span class="score-denominator"> / 100</span>
    </div>
  </div>
</template>
