<script setup>
// 研学工具面板：路线规划 + 任务单生成
import { onMounted, ref, inject } from 'vue'
import { generateRoute, generateTasks, getVenues } from '../api'
import MarkdownView from './MarkdownView.vue'

const grade = inject('grade')

const venues = ref([])
const GRADE_LABEL = {
  primary_low: '小学低年级', primary_high: '小学高年级', junior: '初中', senior: '高中',
}

// ---- 路线规划 ----
const theme = ref('')
const days = ref('一日')
const routeResult = ref('')
const routeLoading = ref(false)
const routeError = ref('')
const THEME_OPTIONS = [
  { value: '', label: '综合红色文化' },
  { value: '辛亥革命', label: '辛亥首义' },
  { value: '党史', label: '党史转折' },
  { value: '工运', label: '工人运动' },
  { value: '抗战', label: '抗战烽火' },
]

async function makeRoute() {
  routeLoading.value = true
  routeResult.value = ''
  routeError.value = ''
  try {
    const { data } = await generateRoute({ grade: grade.value, theme: theme.value, days: days.value })
    routeResult.value = data.answer
  } catch (e) {
    routeError.value = e.response?.data?.detail || e.message
  } finally {
    routeLoading.value = false
  }
}

// ---- 任务单 ----
const venue = ref('')
const taskResult = ref('')
const taskLoading = ref(false)
const taskError = ref('')

async function makeTasks() {
  if (!venue.value) return
  taskLoading.value = true
  taskResult.value = ''
  taskError.value = ''
  try {
    const { data } = await generateTasks({ grade: grade.value, venue: venue.value })
    taskResult.value = data.answer
  } catch (e) {
    taskError.value = e.response?.data?.detail || e.message
  } finally {
    taskLoading.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await getVenues()
    venues.value = data.venues
    if (venues.value.length) venue.value = venues.value[0].name
  } catch { /* 后端未启动时静默 */ }
})
</script>

<template>
  <div class="tools-grid">
    <!-- 研学路线 -->
    <section class="card tool-card">
      <h2 class="section-title">研学路线规划</h2>
      <div class="form-row">
        <label>研学主题</label>
        <select v-model="theme">
          <option v-for="t in THEME_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
      </div>
      <div class="form-row">
        <label>计划时长</label>
        <select v-model="days">
          <option>半日</option>
          <option>一日</option>
        </select>
      </div>
      <p class="form-tip">当前学段：<b>{{ GRADE_LABEL[grade] }}</b>（在页顶可切换，路线与讲解深度将自动适配）</p>
      <button class="btn" :disabled="routeLoading" @click="makeRoute">
        {{ routeLoading ? '规划中…' : '生成研学路线' }}
      </button>

      <div v-if="routeLoading" class="loading-row"><span class="loading-dots"><i /><i /><i /></span>正在结合史料为{{ GRADE_LABEL[grade] }}同学设计路线…</div>
      <div v-if="routeError" class="err">⚠️ {{ routeError }}</div>
      <MarkdownView v-if="routeResult" :content="routeResult" class="result-box" />
    </section>

    <!-- 研学任务单 -->
    <section class="card tool-card">
      <h2 class="section-title">研学任务单生成</h2>
      <div class="form-row">
        <label>选择场馆</label>
        <select v-model="venue">
          <option v-for="v in venues" :key="v.name" :value="v.name">{{ v.name }}</option>
        </select>
      </div>
      <p class="form-tip">任务将按学段梯度设计：观察 → 记录 → 思考 → 表达</p>
      <button class="btn" :disabled="taskLoading || !venue" @click="makeTasks">
        {{ taskLoading ? '生成中…' : '生成任务单' }}
      </button>

      <div v-if="taskLoading" class="loading-row"><span class="loading-dots"><i /><i /><i /></span>正在为「{{ venue }}」设计{{ GRADE_LABEL[grade] }}任务单…</div>
      <div v-if="taskError" class="err">⚠️ {{ taskError }}</div>
      <MarkdownView v-if="taskResult" :content="taskResult" class="result-box" />
    </section>
  </div>
</template>

<style scoped>
.tools-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .tools-grid { grid-template-columns: 1fr; } }

.tool-card { display: flex; flex-direction: column; gap: 12px; }

.form-row { display: flex; align-items: center; gap: 12px; }
.form-row label { font-size: 13.5px; color: var(--ink-light); flex: none; width: 64px; }
.form-row select {
  flex: 1;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  background: #fff;
  outline: none;
}
.form-row select:focus { border-color: var(--red-600); }

.form-tip { font-size: 12.5px; color: var(--ink-light); margin: 0; }
.form-tip b { color: var(--red-700); }

.loading-row { display: flex; align-items: center; gap: 10px; color: var(--ink-light); font-size: 13.5px; }
.err { color: #b03030; font-size: 13px; }
.result-box {
  border-top: 1px dashed var(--line);
  padding-top: 12px;
  max-height: 560px;
  overflow-y: auto;
}
</style>
