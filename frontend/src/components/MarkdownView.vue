<script setup>
// 轻量 Markdown 渲染组件（marked + 基础净化 + 引用角标 [n] 可点击溯源）
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  content: { type: String, default: '' },
})
const emit = defineEmits(['cite'])

marked.setOptions({ breaks: true, gfm: true })

const html = computed(() => {
  // 先归一化模型可能输出的 【[1]】 形式，再渲染 markdown；
  // 在渲染结果上替换 [1]（此时 markdown 链接已转为 <a>，不会误伤）
  const md = String(props.content || '').replace(/【\s*\[(\d{1,2})\]\s*】/g, '[$1]')
  return String(marked.parse(md, { async: false }))
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/on\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\[(\d{1,2})\]/g, '<sup class="cite" data-cite="$1">$1</sup>')
})

function onClick(e) {
  const sup = e.target.closest('sup.cite')
  if (sup) emit('cite', Number(sup.dataset.cite))
}
</script>

<template>
  <div class="md-body" v-html="html" @click="onClick" />
</template>
