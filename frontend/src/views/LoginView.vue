<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ApiError } from '../api'
import { login } from '../auth'
import { recommendationsRoute } from '../utils/recommendationsRoute'

const route = useRoute()
const router = useRouter()
const form = ref<FormInstance>()
const credentials = reactive({ username: '', password: '' })
const rules: FormRules<typeof credentials> = {
  username: [{ required: true, whitespace: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const submitting = ref(false)
const error = ref('')
const accounts = [
  { label: '科研用户', username: 'research_demo' },
  { label: '企业用户', username: 'enterprise_demo' },
]

function selectAccount(username: string) {
  credentials.username = username
  form.value?.clearValidate('username')
  error.value = ''
}

function redirectTarget() {
  const target = route.query.redirect
  if (typeof target !== 'string' || !target.startsWith('/') || /^\/[\\/]/.test(target)) return
  if (router.resolve(target).meta.requiresAuth) return target
}

function errorMessage(cause: unknown) {
  if (cause instanceof ApiError) {
    if (cause.httpStatus === 401) return '用户名或密码错误，请核对后重试。'
    if (cause.httpStatus === 503) return '登录服务暂时不可用，请稍后重试。'
    if (cause.httpStatus === undefined) return '无法连接登录服务，请检查网络后重试。'
  }
  return '登录失败，请稍后重试。'
}

async function submit() {
  if (submitting.value || !form.value) return
  submitting.value = true
  error.value = ''
  try {
    if (!(await form.value.validate().catch(() => false))) return
    const user = await login(credentials.username.trim(), credentials.password)
    credentials.password = ''
    await router.replace(redirectTarget() ?? recommendationsRoute(user.role))
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="login-panel tool-panel" aria-labelledby="login-heading">
    <header>
      <h1 id="login-heading">登录</h1>
      <p>课程演示账号，非真实用户体系。</p>
    </header>

    <div class="account-options" role="group" aria-label="演示账号快捷填充">
      <el-button
        v-for="account in accounts"
        :key="account.username"
        :disabled="submitting"
        :aria-pressed="credentials.username === account.username"
        @click="selectAccount(account.username)"
      >
        <span class="account-option">
          <el-tag size="small" effect="plain" disable-transitions>{{ account.label }}</el-tag>
          <span>{{ account.username }}</span>
        </span>
      </el-button>
    </div>

    <el-alert
      v-if="error || route.query.expired === '1'"
      class="login-alert"
      :title="error || '登录已失效，请重新登录。'"
      :type="error ? 'error' : 'warning'"
      :closable="false"
      show-icon
    />
    <el-form
      ref="form"
      :model="credentials"
      :rules="rules"
      :disabled="submitting"
      label-position="top"
      @submit.prevent="submit"
    >
      <el-form-item label="用户名" prop="username">
        <el-input v-model="credentials.username" name="username" autocomplete="username" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input
          v-model="credentials.password"
          name="password"
          type="password"
          autocomplete="current-password"
        />
      </el-form-item>
      <el-button type="primary" native-type="submit" :loading="submitting">登录</el-button>
    </el-form>
  </section>
</template>

<style scoped>
.login-panel {
  max-width: 472px;
  margin: 20px auto 48px;
  padding: 28px;
}
.login-panel header p {
  margin-top: 6px;
  color: var(--muted);
}
.account-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 20px 0;
}
.account-options .el-button {
  height: auto;
  min-height: 38px;
  margin: 0;
}
.account-options .el-button[aria-pressed='true'] {
  border-color: var(--accent);
  background: var(--el-color-primary-light-9);
}
.account-option {
  display: flex;
  align-items: center;
  gap: 6px;
}
.login-alert {
  margin-bottom: 18px;
}
@media (max-width: 760px) {
  .login-panel {
    margin-top: 0;
    padding: 20px;
  }
}
</style>
