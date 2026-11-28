<script setup lang="ts">
import { onScopeDispose, ref, watch } from 'vue'
import { api, normalizeIntentContact } from '../api'
import { auth } from '../auth'
import { hasApiStatus, intentErrorMessage } from '../composables/useIntentActions'
import type { IntentContact } from '../types'

const props = defineProps<{ intentId: string }>()
const contacts = ref<IntentContact['contacts']>([])
const loading = ref(false)
const error = ref('')
let revision = 0

async function load() {
  const request = ++revision
  const session = auth.token
  const intentId = props.intentId
  const isCurrent = () =>
    request === revision && session === auth.token && intentId === props.intentId
  contacts.value = []
  error.value = ''
  loading.value = Boolean(session)
  if (!session) return
  try {
    const { data } = await api.getIntentContact(intentId)
    if (isCurrent()) {
      contacts.value = normalizeIntentContact(data).contacts.filter(
        (contact) => contact.name || contact.email || contact.phone,
      )
    }
  } catch (cause) {
    if (!isCurrent()) return
    error.value = hasApiStatus(cause, 403)
      ? '暂不可查看联系方式（需双方确认且具访问权限）'
      : intentErrorMessage(cause, '暂时无法加载演示联系方式，请重试')
  } finally {
    if (isCurrent()) loading.value = false
  }
}

watch([() => props.intentId, () => auth.token], load, { immediate: true })
onScopeDispose(() => revision++)
</script>

<template>
  <div class="intent-contact" :aria-busy="loading">
    <div class="contact-heading">
      <el-tag type="warning" effect="light" disable-transitions>演示联系方式</el-tag>
      <el-button v-if="!loading" size="small" @click="load">{{
        error ? '重试' : '刷新联系方式'
      }}</el-button>
    </div>
    <p class="contact-note">当前为模拟联系信息，仅用于流程展示。</p>
    <p v-if="loading" class="contact-note" role="status">正在读取演示联系方式…</p>
    <el-alert v-else-if="error" :title="error" type="warning" :closable="false" show-icon />
    <ul v-else-if="contacts.length" class="contact-list">
      <li v-for="(contact, index) in contacts" :key="index">
        <h3>
          {{
            contact.role === 'researcher'
              ? '科研方联系人'
              : contact.role === 'enterprise'
                ? '企业方联系人'
                : '演示联系资料'
          }}
        </h3>
        <dl>
          <div v-if="contact.name">
            <dt>姓名</dt>
            <dd>{{ contact.name }}</dd>
          </div>
          <div v-if="contact.email">
            <dt>邮箱</dt>
            <dd>{{ contact.email }}</dd>
          </div>
          <div v-if="contact.phone">
            <dt>电话</dt>
            <dd>{{ contact.phone }}</dd>
          </div>
        </dl>
      </li>
    </ul>
    <p v-else class="contact-note">暂无演示联系资料。</p>
  </div>
</template>

<style scoped>
.intent-contact {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 16px;
  background: var(--el-bg-color-page);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.contact-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.contact-heading .el-tag {
  font-weight: 600;
}
.contact-note {
  color: var(--muted);
  font-size: 13px;
}
.contact-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 4px 0 0;
  padding: 0;
  list-style: none;
}
.contact-list li {
  padding: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
}
.contact-list dl {
  display: grid;
  gap: 4px;
  margin-top: 6px;
}
.contact-list dl div {
  display: grid;
  grid-template-columns: 3em minmax(0, 1fr);
  gap: 8px;
}
.contact-list dt {
  color: var(--muted);
}
.contact-list dd {
  margin: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 760px) {
  .intent-contact {
    padding: 12px;
  }
  .contact-list {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
