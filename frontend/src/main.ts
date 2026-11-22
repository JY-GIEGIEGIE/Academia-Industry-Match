import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Recommendations from './views/Recommendations.vue'
import MatchDetail from './views/MatchDetail.vue'
import './style.css'
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/recommendations' },
    { path: '/recommendations', component: Recommendations },
    { path: '/matches/:id', component: MatchDetail },
    { path: '/:pathMatch(.*)*', component: MatchDetail },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.path === from.path) return false
    return { top: 0 }
  },
})
router.afterEach((to) => {
  document.title = (to.path.startsWith('/matches/') ? '匹配详情' : '为你推荐') + ' · 产学研对接'
})
createApp(App).use(router).mount('#app')
