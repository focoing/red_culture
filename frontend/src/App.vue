<script setup>
import { ref, provide } from 'vue'
import GradeSelector from './components/GradeSelector.vue'
import ChatPanel from './components/ChatPanel.vue'
import VenuePanel from './components/VenuePanel.vue'
import StudyTools from './components/StudyTools.vue'

const grade = ref('primary_high') // 全局学段状态
provide('grade', grade)

const tab = ref('chat')
const tabs = [
  { key: 'chat', label: '智能问答' },
  { key: 'venues', label: '场馆导览' },
  { key: 'tools', label: '研学工具' },
]
</script>

<template>
  <header class="site-header">
    <svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="12" fill="rgba(255,255,255,0.14)" />
      <path d="M32 12l6 12 13 2-9.5 9 2.5 13-12-6.5L20 48l2.5-13L13 26l13-2z" fill="#f5d78e" />
    </svg>
    <div>
      <h1>武汉红色文化导览小助手</h1>
      <div class="subtitle">AI 研学导览 · 史料查询 · 路线规划 · 任务生成（RAG 本地知识库）</div>
    </div>
    <div class="header-right">
      <GradeSelector v-model="grade" />
    </div>
  </header>

  <main class="main-wrap">
    <nav class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="tab-btn"
        :class="{ active: tab === t.key }"
        @click="tab = t.key"
      >{{ t.label }}</button>
    </nav>

    <ChatPanel v-show="tab === 'chat'" />
    <VenuePanel v-show="tab === 'venues'" />
    <StudyTools v-show="tab === 'tools'" />
  </main>
</template>
