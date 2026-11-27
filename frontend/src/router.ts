import { watch } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { auth, restoreSession } from './auth'
import { recommendationsRoute } from './utils/recommendationsRoute'

const PublishView = () => import('./views/PublishView.vue')
const MatchDetail = () => import('./views/MatchDetail.vue')

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/recommendations' },
    {
      path: '/login',
      name: 'login',
      component: () => import('./views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/recommendations',
      component: () => import('./views/Recommendations.vue'),
      meta: { requiresAuth: true, title: '为你推荐' },
    },
    {
      path: '/publish',
      name: 'publish',
      component: PublishView,
      meta: { requiresAuth: true },
    },
    {
      path: '/publish/achievement',
      name: 'publish-achievement',
      component: PublishView,
      meta: { requiresAuth: true },
    },
    {
      path: '/publish/demand',
      name: 'publish-demand',
      component: PublishView,
      meta: { requiresAuth: true },
    },
    {
      path: '/matches/:id',
      name: 'match-detail',
      component: MatchDetail,
      meta: { requiresAuth: true, title: '匹配详情' },
    },
    {
      path: '/intents',
      component: () => import('./views/IntentsView.vue'),
      meta: { requiresAuth: true, title: '合作意向' },
    },
    {
      path: '/:pathMatch(.*)*',
      component: MatchDetail,
      meta: { requiresAuth: true, title: '匹配详情' },
    },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.path === from.path) return false
    return { top: 0 }
  },
})

function loginRoute(redirect: string) {
  return {
    name: 'login',
    query: { redirect, expired: auth.sessionExpired ? '1' : undefined },
    replace: true,
  }
}

router.beforeEach(async (to) => {
  await restoreSession()
  if (to.meta.requiresAuth && !auth.isAuthenticated) return loginRoute(to.fullPath)
  if (auth.user) {
    if (to.name === 'login') return { ...recommendationsRoute(auth.user.role), replace: true }
    if (to.path === '/recommendations') {
      const ownRoute = recommendationsRoute(auth.user.role, to.query)
      if (to.query.view !== ownRoute.query.view) {
        return { ...ownRoute, hash: to.hash, replace: true }
      }
    }
  }
})

router.afterEach((to, _from, failure) => {
  if (failure) return
  const title = to.meta.title ?? (auth.isResearcher ? '发布成果' : '发布需求')
  document.title = `${title} · 产学研对接`
})

watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    const route = router.currentRoute.value
    if (!authenticated && auth.sessionExpired && route.meta.requiresAuth) {
      void router.replace(loginRoute(route.fullPath))
    }
  },
)
