<script setup>
// 研学工具面板：单卡片「研学方案规划」——路线 + 交通 + 任务单一体生成
import { onMounted, reactive, ref, inject } from 'vue'
import { generateRoute, generateTasks, getTransitPlan, getVenues } from '../api'
import MarkdownView from './MarkdownView.vue'

const grade = inject('grade')

const venues = ref([])
const GRADE_LABEL = {
  primary_low: '小学低年级', primary_high: '小学高年级', junior: '初中', senior: '高中',
}

// ---- 方案表单 ----
const theme = ref('')
const days = ref('一日')
const picked = ref([]) // 已选场馆名（勾选顺序即游览顺序）
const THEME_OPTIONS = [
  { value: '', label: '综合红色文化' },
  { value: '辛亥革命', label: '辛亥首义' },
  { value: '党史', label: '党史转折' },
  { value: '工运', label: '工人运动' },
  { value: '抗战', label: '抗战烽火' },
]

function togglePick(name) {
  const i = picked.value.indexOf(name)
  if (i >= 0) picked.value.splice(i, 1)
  else if (picked.value.length < 6) picked.value.push(name)
}

// ---- 方案结果 ----
const routeResult = ref('')
const routeLoading = ref(false)
const routeError = ref('')
const transit = ref(null)   // {available, legs, message}
const transitLoading = ref(false)
const transitError = ref('')
const taskVenue = ref('')   // 未勾选场馆时，任务单用下拉选择
const tasks = reactive({})  // venue -> {result, loading, error}
const SEG_ICON = { walk: '🚶', subway: '🚇', bus: '🚌' }

// 一键生成：路线 + 换乘（选了 ≥2 个场馆时）并行请求
async function makePlan() {
  routeLoading.value = true
  routeResult.value = ''
  routeError.value = ''
  const wantTransit = picked.value.length >= 2
  if (wantTransit) { transitLoading.value = true; transit.value = null; transitError.value = '' }
  const routeJob = generateRoute({ grade: grade.value, theme: theme.value, days: days.value, venues: picked.value })
    .then(({ data }) => { routeResult.value = data.answer })
    .catch((e) => { routeError.value = e.response?.data?.detail || e.message })
  const transitJob = wantTransit
    ? getTransitPlan(picked.value)
      .then(({ data }) => { transit.value = data })
      .catch((e) => { transitError.value = e.response?.data?.detail || e.message })
      .finally(() => { transitLoading.value = false })
    : Promise.resolve()
  await Promise.all([routeJob, transitJob])
  routeLoading.value = false
}

// 为指定场馆生成任务单（选中的场馆逐个懒生成）
async function makeTasks(name) {
  if (!name || tasks[name]?.loading) return
  tasks[name] = { result: '', loading: true, error: '' }
  try {
    const { data } = await generateTasks({ grade: grade.value, venue: name })
    tasks[name] = { result: data.answer, loading: false, error: '' }
  } catch (e) {
    tasks[name] = { result: '', loading: false, error: e.response?.data?.detail || e.message }
  }
}

onMounted(async () => {
  try {
    const { data } = await getVenues()
    venues.value = data.venues
    if (venues.value.length) taskVenue.value = venues.value[0].name
  } catch { /* 后端未启动时静默 */ }
})
</script>

<template>
  <div class="tools-wrap">
    <section class="card tool-card">
      <h2 class="section-title">研学方案规划</h2>
      <p class="form-tip">
        一次生成完整研学方案：行程路线 + 场馆交通 + 研学任务单。
        当前学段：<b>{{ GRADE_LABEL[grade] }}</b>（页顶可切换，方案自动适配）
      </p>

      <!-- 表单 -->
      <div class="form-row">
        <label>研学主题</label>
        <select v-model="theme">
          <option v-for="t in THEME_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
        <label>计划时长</label>
        <select v-model="days">
          <option>半日</option>
          <option>一日</option>
        </select>
      </div>

      <div class="form-block">
        <div class="block-label">选择场馆（可选 2-6 个，不选则按主题自动推荐）</div>
        <div class="venue-chips">
          <button
            v-for="v in venues" :key="v.name"
            class="chip" :class="{ on: picked.includes(v.name) }"
            :disabled="!picked.includes(v.name) && picked.length >= 6"
            @click="togglePick(v.name)"
          >{{ v.name }}</button>
        </div>
        <div v-if="picked.length" class="picked-line">当前顺序：{{ picked.join(' → ') }}</div>
      </div>

      <button class="btn" :disabled="routeLoading" @click="makePlan">
        {{ routeLoading ? '规划中…' : '一键生成研学方案' }}
      </button>

      <!-- 生成状态 -->
      <div v-if="routeLoading" class="loading-row">
        <span class="loading-dots"><i /><i /><i /></span>
        正在结合史料为{{ GRADE_LABEL[grade] }}同学设计研学方案…
      </div>
      <div v-if="routeError" class="err">⚠️ 路线生成失败：{{ routeError }}</div>

      <!-- 结果一：行程路线 -->
      <div v-if="routeResult" class="plan-section">
        <div class="plan-head">🗺️ 行程路线</div>
        <MarkdownView :content="routeResult" />
      </div>

      <!-- 结果二：场馆交通换乘 -->
      <div v-if="transitLoading" class="loading-row">
        <span class="loading-dots"><i /><i /><i /></span>正在请求高德换乘规划…
      </div>
      <div v-if="transitError" class="err">⚠️ {{ transitError }}</div>
      <div v-if="transit && !transit.available" class="form-tip">⚠️ {{ transit.message }}</div>
      <div v-if="transit && transit.available" class="plan-section">
        <div class="plan-head">🚇 场馆交通换乘</div>
        <div v-for="(leg, i) in transit.legs" :key="i" class="leg">
          <div class="leg-head">
            <b>{{ leg.from }}</b><span class="leg-arrow">→</span><b>{{ leg.to }}</b>
          </div>
          <div v-if="leg.error" class="err">{{ leg.error }}</div>
          <div v-for="(plan, j) in leg.plans" :key="j" class="plan">
            <div class="plan-summary">
              <span>{{ plan.summary }}</span>
              <span class="plan-meta">{{ plan.duration }} · {{ plan.distance }}</span>
            </div>
            <div class="plan-segments">
              <template v-for="(seg, k) in plan.segments" :key="k">
                <span class="seg"><i>{{ SEG_ICON[seg.type] || '🚌' }}</i>{{ seg.text }}</span>
                <span v-if="k < plan.segments.length - 1" class="seg-arrow">›</span>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 结果三：研学任务单 -->
      <div class="plan-section">
        <div class="plan-head">📋 研学任务单</div>
        <p class="form-tip">任务按学段梯度设计：观察 → 记录 → 思考 → 表达。按需为各场馆生成。</p>

        <!-- 勾选了场馆：逐馆生成 -->
        <template v-if="picked.length">
          <div v-for="name in picked" :key="name" class="task-item">
            <div class="task-bar">
              <b>{{ name }}</b>
              <button class="btn ghost mini" :disabled="tasks[name]?.loading" @click="makeTasks(name)">
                {{ tasks[name]?.loading ? '生成中…' : tasks[name]?.result ? '重新生成' : '生成任务单' }}
              </button>
            </div>
            <div v-if="tasks[name]?.loading" class="loading-row">
              <span class="loading-dots"><i /><i /><i /></span>正在设计任务单…
            </div>
            <div v-if="tasks[name]?.error" class="err">⚠️ {{ tasks[name].error }}</div>
            <MarkdownView v-if="tasks[name]?.result" :content="tasks[name].result" class="task-result" />
          </div>
        </template>

        <!-- 未勾选场馆：下拉选择生成 -->
        <template v-else>
          <div class="form-row">
            <label>选择场馆</label>
            <select v-model="taskVenue">
              <option v-for="v in venues" :key="v.name" :value="v.name">{{ v.name }}</option>
            </select>
            <button class="btn mini" :disabled="!taskVenue || tasks[taskVenue]?.loading" @click="makeTasks(taskVenue)">
              {{ tasks[taskVenue]?.loading ? '生成中…' : '生成任务单' }}
            </button>
          </div>
          <div v-if="taskVenue && tasks[taskVenue]?.loading" class="loading-row">
            <span class="loading-dots"><i /><i /><i /></span>正在为「{{ taskVenue }}」设计任务单…
          </div>
          <div v-if="taskVenue && tasks[taskVenue]?.error" class="err">⚠️ {{ tasks[taskVenue].error }}</div>
          <MarkdownView v-if="taskVenue && tasks[taskVenue]?.result" :content="tasks[taskVenue].result" class="task-result" />
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tools-wrap { max-width: 900px; margin: 0 auto; }
.tool-card { display: flex; flex-direction: column; gap: 14px; }

.form-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.form-row label { font-size: 13.5px; color: var(--ink-light); flex: none; }
.form-row select {
  flex: 1; min-width: 130px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  background: #fff;
  outline: none;
}
.form-row select:focus { border-color: var(--red-600); }

.form-block { display: flex; flex-direction: column; gap: 8px; }
.block-label { font-size: 13.5px; color: var(--ink-light); }
.venue-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  border: 1px solid var(--line); background: #fff; color: var(--ink);
  border-radius: 999px; padding: 5px 14px; font-size: 12.5px; cursor: pointer; transition: all 0.15s;
}
.chip:hover:not(:disabled) { border-color: var(--red-600); color: var(--red-700); }
.chip.on { background: var(--red-700); border-color: var(--red-700); color: #fff; }
.chip:disabled { opacity: 0.4; cursor: not-allowed; }
.picked-line { font-size: 12.5px; color: var(--red-800); background: var(--red-50); border-radius: 8px; padding: 6px 10px; }

.form-tip { font-size: 12.5px; color: var(--ink-light); margin: 0; }
.form-tip b { color: var(--red-700); }

.loading-row { display: flex; align-items: center; gap: 10px; color: var(--ink-light); font-size: 13.5px; }
.err { color: #b03030; font-size: 13px; }

/* ---- 方案结果分区 ---- */
.plan-section { border-top: 1px dashed var(--line); padding-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.plan-head { font-size: 15px; font-weight: 700; color: var(--red-800); }

.leg { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.leg-head { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--red-800); margin-bottom: 8px; }
.leg-arrow { color: var(--ink-light); }
.plan { border-top: 1px dashed var(--line); padding-top: 8px; margin-top: 6px; }
.plan-summary { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; font-weight: 700; color: var(--ink); }
.plan-meta { flex: none; font-weight: 400; font-size: 12px; color: var(--ink-light); }
.plan-segments { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }
.seg {
  display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  background: var(--red-50); border-radius: 6px; padding: 3px 8px; color: var(--ink);
}
.seg i { font-style: normal; }
.seg-arrow { color: var(--ink-light); font-size: 12px; }

/* ---- 任务单 ---- */
.task-item { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.task-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.task-bar b { font-size: 14px; color: var(--red-800); }
.btn.mini { padding: 5px 14px; font-size: 12.5px; flex: none; }
.task-result { max-height: 480px; overflow-y: auto; }
</style>
