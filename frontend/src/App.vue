<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiMode } from './api'
import { auth, logout } from './auth'
import Icon from './components/Icon.vue'
import { recommendationsRoute } from './utils/recommendationsRoute'

const route = useRoute(),
  router = useRouter()
const showNavigation = computed(() => auth.isAuthenticated && route.name !== 'login')
const recommendations = computed(() => recommendationsRoute(auth.user?.role ?? 'enterprise'))
const backToRecommendations = computed(() =>
  recommendationsRoute(auth.user?.role ?? 'enterprise', route.query),
)
const publishLabel = computed(() => (auth.isResearcher ? '发布成果' : '发布需求'))
const publishActive = computed(
  () => route.path === '/publish' || route.path.startsWith('/publish/'),
)
const showAchievementFooter = computed(
  () =>
    showNavigation.value &&
    (route.path === '/recommendations' ||
      route.name === 'match-detail' ||
      ((route.name === 'publish' || route.name === 'publish-achievement') && auth.isResearcher)),
)

function signOut() {
  logout()
  void router.replace({ name: 'login' })
}
function skipToContent() {
  document.getElementById('main-content')?.focus()
}
</script>
<template>
  <a class="skip-link" href="#main-content" @click.prevent="skipToContent">跳到主要内容</a>
  <header class="app-header">
    <div class="header-inner">
      <RouterLink class="brand" :to="showNavigation ? recommendations : { name: 'login' }">
        产学研对接
      </RouterLink>
      <template v-if="showNavigation">
        <nav class="primary-nav" aria-label="主导航">
          <RouterLink :to="route.path === '/recommendations' ? route.fullPath : recommendations">
            为你推荐
          </RouterLink>
          <RouterLink
            to="/publish"
            :class="{ 'nav-active': publishActive }"
            :aria-current="publishActive ? 'page' : undefined"
          >
            {{ publishLabel }}
          </RouterLink>
          <RouterLink to="/intents">合作意向</RouterLink>
        </nav>
        <RouterLink
          v-if="route.name === 'match-detail'"
          class="back-link"
          :to="backToRecommendations"
        >
          <Icon name="back" />返回推荐列表
        </RouterLink>
        <div class="header-user">
          <el-tag
            v-if="apiMode === 'mock'"
            type="info"
            size="small"
            effect="plain"
            disable-transitions
            >本地模拟</el-tag
          >
          <el-tag class="role-badge" size="small" effect="plain" disable-transitions>{{
            auth.isResearcher ? '科研端' : '企业端'
          }}</el-tag>
          <span class="header-user-name" :title="auth.user?.username">{{
            auth.user?.username
          }}</span>
          <el-button size="small" @click="signOut">退出登录</el-button>
        </div>
      </template>
    </div>
  </header>
  <div class="page-shell">
    <main id="main-content" tabindex="-1"><RouterView /></main>
    <footer v-if="showAchievementFooter" class="app-footer">
      <span>原始成果来自 OpenAlex，以原文为准</span>
    </footer>
  </div>
</template>
