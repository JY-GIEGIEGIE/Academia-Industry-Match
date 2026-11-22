<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import Icon from './components/Icon.vue'
const route = useRoute(),
  router = useRouter()
function switchView(view: string) {
  router.push({ path: '/recommendations', query: { view } })
}
</script>
<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="app-header">
    <div class="header-inner">
      <RouterLink class="brand" :to="{ path: '/recommendations', query: route.query }"
        >产学研对接</RouterLink
      >
      <nav v-if="route.path === '/recommendations'" class="perspective-tabs" aria-label="使用视角">
        <button
          :aria-pressed="route.query.view !== 'research'"
          :class="{ active: route.query.view !== 'research' }"
          @click="switchView('enterprise')"
        >
          企业端
        </button>
        <button
          :aria-pressed="route.query.view === 'research'"
          :class="{ active: route.query.view === 'research' }"
          @click="switchView('research')"
        >
          科研端
        </button>
      </nav>
      <RouterLink v-else class="back-link" :to="{ path: '/recommendations', query: route.query }"
        ><Icon name="back" />返回推荐列表</RouterLink
      >
    </div>
  </header>
  <div class="page-shell">
    <aside class="demo-notice" aria-label="演示说明">
      <Icon name="info" />
      <p><strong>演示说明</strong><span>需求与企业为模拟资料，匹配评分和分析仅用于展示。</span></p>
    </aside>
    <main id="main-content" tabindex="-1"><RouterView /></main>
    <footer class="app-footer">
      <span>原始成果来自 OpenAlex · 中文说明与分类为演示整理，原文为准</span
      ><span>仅演示推荐与详情流程</span>
    </footer>
  </div>
</template>
