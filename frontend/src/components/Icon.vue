<script setup lang="ts">
defineProps<{ name: 'back' | 'next' | 'info' | 'external' | 'chevron' }>()
</script>
<template>
  <svg
    class="icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'back'"><path d="m14 6-6 6 6 6M8 12h12" /></template>
    <template v-else-if="name === 'next'"><path d="m10 6 6 6-6 6M4 12h12" /></template>
    <template v-else-if="name === 'external'">
      <path d="M14 4h6v6M20 4l-9 9M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" />
    </template>
    <template v-else-if="name === 'chevron'"><path d="m6 9 6 6 6-6" /></template>
    <template v-else>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7h.01" />
    </template>
  </svg>
</template>
