<script setup>
// 轻量 Markdown 渲染组件（marked + 基础净化）
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  content: { type: String, default: '' },
})

marked.setOptions({ breaks: true, gfm: true })

const html = computed(() => {
  const raw = marked.parse(props.content || '', { async: false })
  // 移除脚本/事件属性，防止注入
  return String(raw)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/on\w+\s*=\s*"[^"]*"/gi, '')
})
</script>

<template>
  <div class="md-body" v-html="html" />
</template>
