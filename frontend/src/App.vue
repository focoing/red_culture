<script setup>
import { ref, provide } from 'vue'
import GradeSelector from './components/GradeSelector.vue'
import ChatPanel from './components/ChatPanel.vue'
import TourPanel from './components/TourPanel.vue'
import StudyTools from './components/StudyTools.vue'

const grade = ref('primary_high') // 全局学段状态
provide('grade', grade)

// 导览为主：场馆导览（默认首页）-> 研学工具 -> 史料问答（随行辅助）
const tab = ref('tour')
const tabs = [
  { key: 'tour', label: '场馆导览' },
  { key: 'tools', label: '研学工具' },
  { key: 'chat', label: '史料问答' },
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
      <div class="subtitle">场馆随行导览｜红色故事讲解｜研学任务生成｜史料查询</div>
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

    <TourPanel v-show="tab === 'tour'" />
    <StudyTools v-show="tab === 'tools'" />
    <ChatPanel v-show="tab === 'chat'" />
  </main>
</template>
