<script setup>
// 场馆导览面板：场馆卡片 + 单馆讲解词生成（按学段）
import { onMounted, ref, inject } from 'vue'
import { getVenues } from '../api'
import MarkdownView from './MarkdownView.vue'

const grade = inject('grade')
const venues = ref([])
const themes = ref([])
const activeTheme = ref('')
const loading = ref(false)

const detail = ref(null) // 当前展开讲解的场馆
const explainLoading = ref(false)
const explanation = ref('')
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await getVenues()
    venues.value = data.venues
    themes.value = data.themes
  } catch (e) {
    error.value = '无法加载场馆数据，请确认后端已启动'
  }
})

const filtered = () =>
  activeTheme.value ? venues.value.filter((v) => v.theme === activeTheme.value) : venues.value

const THEME_LABEL = { 辛亥革命: '辛亥首义', 党史: '党史转折', 工运: '工人运动', 抗战: '抗战烽火' }

async function openExplain(venue) {
  if (detail.value === venue.name) { detail.value = null; return }
  detail.value = venue.name
  explanation.value = ''
  explainLoading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/explanation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grade: grade.value, venue: venue.name }),
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '生成失败')
    explanation.value = data.answer
  } catch (e) {
    error.value = e.message
  } finally {
    explainLoading.value = false
  }
}
</script>

<template>
  <div>
    <div class="theme-bar">
      <button class="tab-btn" :class="{ active: !activeTheme }" @click="activeTheme = ''">全部场馆</button>
      <button
        v-for="t in themes" :key="t"
        class="tab-btn" :class="{ active: activeTheme === t }"
        @click="activeTheme = t"
      >{{ THEME_LABEL[t] || t }}</button>
    </div>

    <div v-if="error" class="empty-tip">{{ error }}</div>

    <div class="venue-grid">
      <div v-for="v in filtered()" :key="v.name" class="card venue-card">
        <div class="venue-head">
          <h3>{{ v.name }}</h3>
          <span class="tag">{{ THEME_LABEL[v.theme] || v.theme }}</span>
        </div>
        <p class="venue-addr">📍 {{ v.address }}</p>
        <p class="venue-meta">🕒 {{ v.opening_hours }}</p>
        <p class="venue-meta">🎫 {{ v.reservation }}</p>
        <p class="venue-meta">⏱ 建议参观：{{ v.suggested_duration }}</p>
        <div class="venue-actions">
          <button class="btn" :disabled="explainLoading" @click="openExplain(v)">
            {{ detail === v.name ? '收起讲解' : '生成讲解词' }}
          </button>
        </div>

        <div v-if="detail === v.name" class="explain-box">
          <div v-if="explainLoading" class="loading-row">
            <span class="loading-dots"><i /><i /><i /></span>
            <span>小助手正在为【{{ grade === 'primary_low' ? '低年级' : grade === 'primary_high' ? '高年级' : grade === 'junior' ? '初中' : '高中' }}同学】撰写讲解词…</span>
          </div>
          <MarkdownView v-else-if="explanation" :content="explanation" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.theme-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.venue-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 16px; }

.venue-card h3 { margin: 0; font-size: 16px; color: var(--red-800); }
.venue-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.venue-addr { font-size: 13px; color: var(--ink); margin: 10px 0 6px; }
.venue-meta { font-size: 12.5px; color: var(--ink-light); margin: 4px 0; }
.venue-actions { margin-top: 12px; }

.explain-box {
  margin-top: 14px;
  border-top: 1px dashed var(--line);
  padding-top: 12px;
  background: var(--red-50);
  border-radius: 10px;
  padding: 12px 14px;
}
.loading-row { display: flex; align-items: center; gap: 10px; color: var(--ink-light); font-size: 13.5px; }
</style>
