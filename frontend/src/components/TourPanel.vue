<script setup>
// 场馆导览面板（产品主打）：选场馆 -> 点位时序线 -> AI 随行讲解 + 打卡 + 研学小任务 + 随行问答
import { computed, inject, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { chatStream, getTourRoute, getVenues, tourExplainStream } from '../api'
import MarkdownView from './MarkdownView.vue'

const grade = inject('grade')

const THEME_LABEL = { 辛亥革命: '辛亥首义', 党史: '党史转折', 工运: '工人运动', 抗战: '抗战烽火' }
const THEME_GLYPH = { 辛亥革命: '首义', 党史: '转折', 工运: '工运', 抗战: '烽火' }

// ================= 选馆视图 =================
const venues = ref([])
const themes = ref([])
const activeTheme = ref('')
const loadError = ref('')
const opening = ref(false)

onMounted(async () => {
  try {
    const { data } = await getVenues()
    venues.value = data.venues
    themes.value = data.themes
  } catch (e) {
    loadError.value = '无法加载场馆数据，请确认后端已启动'
  }
})

const filteredVenues = computed(() =>
  activeTheme.value ? venues.value.filter((v) => v.theme === activeTheme.value) : venues.value)

// 高德 URI 免 Key 跳转：打开高端地图搜索该场馆（可继续发起导航）
const amapLink = (name) =>
  `https://uri.amap.com/search?keyword=${encodeURIComponent(name)}&city=${encodeURIComponent('武汉')}`

// ================= 导览状态 =================
const view = ref('select') // select 选馆 | tour 导览
const venue = ref(null)
const points = ref([])
const cur = ref(0)
const finished = ref(false)
const checked = ref([]) // 已打卡点位 section 标题
const explains = reactive({}) // `${venue}|${grade}|${section}` -> {content, sources, loading, error, done}
const asks = reactive({}) // section -> {messages, input, sending}
const sessionId = ref(null) // 本场馆导览共用的问答会话（换馆重置）
const pointCard = ref(null)

const point = computed(() => points.value[cur.value] || null)
const nextPoint = computed(() => points.value[cur.value + 1] || null)
const progress = computed(() =>
  points.value.length ? ((cur.value + 1) / points.value.length) * 100 : 0)
const checkKey = computed(() => `redtour-checkin-${venue.value?.name || ''}`)

// 讲解缓存 key 必须含场馆名：不同场馆的「场馆概况」是完全不同的讲解，
// 缺场馆名会导致换馆后回放上一馆的讲解内容
function explainKey(section) { return `${venue.value?.name || ''}|${grade.value}|${section}` }
const explain = computed(() => (point.value ? explains[explainKey(point.value.section)] : null))
const qa = computed(() => {
  if (!point.value) return null
  const k = point.value.section
  if (!asks[k]) asks[k] = { messages: [], input: '', sending: false }
  return asks[k]
})

async function openVenue(v) {
  if (opening.value) return
  opening.value = true
  try {
    const { data } = await getTourRoute(v.name)
    venue.value = data.venue
    points.value = data.points
    try { checked.value = JSON.parse(localStorage.getItem(checkKey.value) || '[]') } catch { checked.value = [] }
    // 换馆隔离：清空上一馆的讲解/问答状态，问答开新会话（避免跨馆串台）
    Object.keys(explains).forEach((k) => delete explains[k])
    Object.keys(asks).forEach((k) => delete asks[k])
    sessionId.value = null
    cur.value = 0
    finished.value = false
    view.value = 'tour'
    loadExplain()
  } catch (e) {
    loadError.value = '导览路线加载失败，请稍后重试'
  } finally {
    opening.value = false
  }
}

function backToSelect() {
  view.value = 'select'
  venue.value = null
  points.value = []
  cur.value = 0
  finished.value = false
}

function goto(i) {
  if (i < 0 || i >= points.value.length) return
  finished.value = false
  cur.value = i
  nextTick(() => pointCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  loadExplain()
}

// ---- 点位讲解（流式，按 场馆+学段+点位 缓存在内存；语义缓存在后端） ----
async function loadExplain(force = false) {
  const p = point.value
  if (!p || !venue.value) return
  const key = explainKey(p.section)
  const existed = explains[key]
  if (!force && existed && (existed.done || existed.loading)) return
  const rec = reactive({ content: '', sources: [], loading: true, error: '', done: false })
  explains[key] = rec
  try {
    await tourExplainStream(
      { venue: venue.value.name, section: p.section, grade: grade.value },
      (type, data) => {
        if (type === 'sources') rec.sources = data
        else if (type === 'delta') rec.content += data
        else if (type === 'done') { rec.content = data; rec.loading = false; rec.done = true }
        else if (type === 'error') { rec.error = data.message || '服务异常'; rec.loading = false }
      },
    )
  } catch (e) {
    rec.error = `无法连接服务：${e.message}`
    rec.loading = false
  }
}

// 学段切换后重新生成本点位讲解（缓存按学段隔离，切回旧学段直接命中内存缓存）
watch(grade, () => { if (view.value === 'tour') loadExplain() })

// ---- 打卡（localStorage 持久化） ----
function saveChecked() { localStorage.setItem(checkKey.value, JSON.stringify(checked.value)) }
function isChecked(section) { return checked.value.includes(section) }
function toggleCheck() {
  const s = point.value?.section
  if (!s) return
  const i = checked.value.indexOf(s)
  if (i >= 0) checked.value.splice(i, 1)
  else checked.value.push(s)
  saveChecked()
}

function next() {
  const s = point.value?.section
  if (s && !checked.value.includes(s)) { checked.value.push(s); saveChecked() } // 前进即打卡
  if (cur.value < points.value.length - 1) goto(cur.value + 1)
  else {
    finished.value = true
    nextTick(() => pointCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}

function restartTour() {
  finished.value = false
  cur.value = 0
  nextTick(() => pointCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  loadExplain()
}

// ---- 随行问答（依附当前点位场景，复用流式问答管线） ----
async function sendQuestion() {
  if (!qa.value) return
  const q = qa.value.input.trim()
  if (!q || qa.value.sending) return
  qa.value.input = ''
  qa.value.messages.push({ role: 'user', content: q })
  const reply = reactive({ role: 'assistant', content: '', sources: [], streaming: true })
  qa.value.messages.push(reply)
  qa.value.sending = true
  try {
    await chatStream(
      {
        question: q, grade: grade.value, session_id: sessionId.value,
        venue: venue.value.name, section: point.value.section,
      },
      (type, data) => {
        if (type === 'meta') sessionId.value = data.session_id
        else if (type === 'sources') reply.sources = data
        else if (type === 'delta') reply.content += data
        else if (type === 'done') { reply.content = data; reply.streaming = false }
        else if (type === 'error') {
          reply.content += `\n\n> ⚠️ 出错了：${data.message || '服务异常'}`
          reply.streaming = false
        }
      },
    )
  } catch (e) {
    reply.content += `\n\n> ⚠️ 无法连接服务：${e.message}`
  } finally {
    reply.streaming = false
    qa.value.sending = false
  }
}

// 点击引用角标 [n]：展开对应史料原文并高亮
function onCite(n, msg, containerId) {
  const s = msg.sources && msg.sources[n - 1]
  if (!s) return
  s._open = true
  nextTick(() => {
    const el = document.getElementById(`${containerId}-${n - 1}`)
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); s._flash = true }
    setTimeout(() => { s._flash = false }, 1600)
  })
}
</script>

<template>
  <!-- ============ 选馆视图 ============ -->
  <div v-if="view === 'select'">
    <div class="tour-hero">
      <div class="hero-deco" aria-hidden="true"></div>
      <div class="hero-inner">
        <div class="hero-kicker">武汉 · 红色场馆研学</div>
        <h2>选一处场馆，让我陪你走进历史现场</h2>
        <p>按导览路线逐站讲解红色故事，沿途抛出研学小任务；有疑问随时提问，我可查询本地史料作答。</p>
        <div class="hero-stats">
          <span><b>{{ venues.length }}</b> 座场馆</span>
          <i></i>
          <span>逐站<b>讲解 + 打卡</b></span>
          <i></i>
          <span>随行<b>史料问答</b></span>
        </div>
      </div>
    </div>

    <div class="theme-bar">
      <button class="tab-btn" :class="{ active: !activeTheme }" @click="activeTheme = ''">全部场馆</button>
      <button
        v-for="t in themes" :key="t"
        class="tab-btn" :class="{ active: activeTheme === t }"
        @click="activeTheme = t"
      >{{ THEME_LABEL[t] || t }}</button>
    </div>

    <div v-if="loadError" class="empty-tip">{{ loadError }}</div>

    <div class="venue-grid">
      <article v-for="v in filteredVenues" :key="v.name" class="card venue-card">
        <div class="venue-cover" :data-theme="v.theme">
          <span class="cover-glyph">{{ THEME_GLYPH[v.theme] || v.theme }}</span>
          <span class="cover-duration">建议参观 {{ v.suggested_duration }}</span>
        </div>
        <div class="venue-body">
          <div class="venue-head">
            <h3>{{ v.name }}</h3>
            <span class="tag">{{ THEME_LABEL[v.theme] || v.theme }}</span>
          </div>
          <p class="venue-addr">{{ v.address }}</p>
          <p class="venue-meta">{{ v.opening_hours }}</p>
          <div class="venue-actions">
            <button class="btn" :disabled="opening" @click="openVenue(v)">
              {{ opening ? '加载中…' : '开始导览 →' }}
            </button>
            <a class="nav-link" :href="amapLink(v.name)" target="_blank" rel="noopener">📍 地图导航</a>
          </div>
        </div>
      </article>
    </div>
  </div>

  <!-- ============ 导览视图 ============ -->
  <div v-else class="tour-layout">
    <!-- 导览头：返回 + 进度 -->
    <div class="card tour-head">
      <button class="btn ghost back-btn" @click="backToSelect">← 换场馆</button>
      <div class="tour-title">
        <h2>{{ venue.name }}</h2>
        <span class="tag gold">{{ THEME_LABEL[venue.theme] || venue.theme }}</span>
      </div>
      <div class="tour-progress">
        <div class="progress-text">
          <b>第 {{ cur + 1 }} / {{ points.length }} 站</b>
          <span>已打卡 {{ checked.length }}/{{ points.length }}</span>
        </div>
        <div class="progress-bar"><i :style="{ width: progress + '%' }" /></div>
      </div>
    </div>

    <div class="tour-body">
      <!-- 点位时间线 -->
      <aside class="card tour-map">
        <div class="map-title">导览路线</div>
        <button
          v-for="(p, i) in points" :key="p.section"
          class="stop" :class="{ current: i === cur, done: i < cur || isChecked(p.section) }"
          @click="goto(i)"
        >
          <span class="stop-dot">{{ (i < cur || isChecked(p.section)) ? '✓' : i + 1 }}</span>
          <span class="stop-info">
            <b>{{ p.title }}</b>
            <em>{{ p.brief }}</em>
          </span>
        </button>
      </aside>

      <!-- 点位卡片 -->
      <section ref="pointCard" class="card point-card">
        <template v-if="point && !finished">
          <div class="point-head">
            <span class="point-no">第 {{ cur + 1 }} 站</span>
            <h3>{{ point.title }}</h3>
            <p class="point-brief">{{ point.brief }}</p>
          </div>

          <!-- AI 讲解 -->
          <div class="explain">
            <div class="explain-toolbar">
              <span class="explain-label">AI 随行讲解 · {{ grade === 'senior' ? '高中' : grade === 'junior' ? '初中' : grade === 'primary_low' ? '小学低年级' : '小学高年级' }}</span>
              <button v-if="explain && explain.done" class="btn ghost mini" @click="loadExplain(true)">重新讲解</button>
            </div>

            <div v-if="explain && explain.loading && !explain.content" class="loading-row">
              <span class="loading-dots"><i /><i /><i /></span>
              <span>正在结合史料撰写本站讲解词…</span>
            </div>
            <div v-if="explain && explain.error" class="err">⚠️ {{ explain.error }}</div>
            <MarkdownView
              v-if="explain && explain.content" :content="explain.content"
              @cite="(n) => onCite(n, explain, 'ex-src')"
            />

            <!-- 讲解参考史料 -->
            <div v-if="explain && explain.done && explain.sources.length" class="sources">
              <div class="sources-title">📚 本站参考史料 · 点击角标或条目查看原文</div>
              <div
                v-for="(s, j) in explain.sources" :key="j"
                :id="`ex-src-${j}`" class="source-item" :class="{ flash: s._flash }"
              >
                <button class="source-head" :disabled="!s.content" @click="s._open = !s._open">
                  <span class="tag">{{ j + 1 }}</span>
                  <span class="tag">{{ s.venue }}</span>
                  <span class="source-snippet">{{ (s.section ? s.section + ' · ' : '') + s.snippet }}…</span>
                  <span v-if="s.content" class="chevron">{{ s._open ? '▲' : '▼' }}</span>
                </button>
                <div v-if="s._open && s.content" class="source-full">{{ s.content }}</div>
              </div>
            </div>
          </div>

          <!-- 随行问答 -->
          <div class="qa-box">
            <div class="qa-title">🤔 关于这一站，随时可以问我</div>
            <div v-if="qa && qa.messages.length" class="qa-msgs">
              <div v-for="(m, i) in qa.messages" :key="i" class="qa-msg" :class="m.role">
                <div class="qa-bubble">
                  <MarkdownView v-if="m.content" :content="m.content" @cite="(n) => onCite(n, m, `qa-${i}`)" />
                  <div v-if="m.streaming" class="loading-dots"><i /><i /><i /></div>
                </div>
              </div>
            </div>
            <div class="qa-input">
              <input
                v-model="qa.input" type="text" :disabled="qa.sending"
                placeholder="比如：这个展区里最值得仔细看的是什么？"
                @keyup.enter="sendQuestion()"
              >
              <button class="btn" :disabled="qa.sending || !qa.input.trim()" @click="sendQuestion()">提问</button>
            </div>
          </div>

          <!-- 底部导航 -->
          <div class="point-foot">
            <button class="btn ghost" :disabled="cur === 0" @click="goto(cur - 1)">← 上一站</button>
            <button class="check-btn" :class="{ done: isChecked(point.section) }" @click="toggleCheck">
              {{ isChecked(point.section) ? '✓ 已打卡' : '打卡这一站' }}
            </button>
            <button v-if="nextPoint" class="btn next-btn" @click="next">
              下一站 · {{ nextPoint.title }} →
            </button>
            <button v-else class="btn next-btn finish-btn" @click="next">完成导览 ✓</button>
          </div>
        </template>

        <!-- 导览完成 -->
        <div v-else-if="finished" class="tour-done">
          <div class="done-badge">✓</div>
          <h3>「{{ venue.name }}」导览完成！</h3>
          <p>本站共 {{ points.length }} 个点位，你打卡了 <b>{{ checked.length }}</b> 个。
            带上研学小任务的答案，去「研学工具」生成完整任务单，或换个场馆继续探索。</p>
          <div class="done-actions">
            <button class="btn ghost" @click="restartTour">再逛一遍</button>
            <button class="btn ghost" @click="backToSelect">换场馆</button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* ===== 选馆：Hero ===== */
.tour-hero {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius);
  background: linear-gradient(120deg, var(--red-900), var(--red-700) 55%, var(--red-600));
  color: #fff;
  padding: 34px 32px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}
.hero-deco {
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(circle at 85% 20%, rgba(245, 215, 142, 0.22), transparent 42%),
    radial-gradient(circle at 12% 85%, rgba(255, 255, 255, 0.08), transparent 40%),
    repeating-linear-gradient(115deg, transparent 0 26px, rgba(255, 255, 255, 0.035) 26px 28px);
}
.hero-inner { position: relative; }
.hero-kicker {
  display: inline-block; font-size: 12px; letter-spacing: 3px;
  border: 1px solid rgba(255, 255, 255, 0.45); border-radius: 999px;
  padding: 3px 12px; margin-bottom: 12px; opacity: 0.92;
}
.hero-inner h2 { margin: 0 0 8px; font-size: 24px; letter-spacing: 1px; }
.hero-inner p { margin: 0; font-size: 13.5px; opacity: 0.88; max-width: 560px; line-height: 1.8; }
.hero-stats { display: flex; align-items: center; gap: 14px; margin-top: 16px; font-size: 13px; opacity: 0.95; flex-wrap: wrap; }
.hero-stats b { color: var(--gold); }
.hero-stats i { width: 1px; height: 14px; background: rgba(255, 255, 255, 0.35); }

/* ===== 选馆：场馆卡片 ===== */
.theme-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.venue-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.venue-card { padding: 0; overflow: hidden; display: flex; flex-direction: column; transition: transform 0.18s, box-shadow 0.18s; }
.venue-card:hover { transform: translateY(-3px); box-shadow: 0 8px 22px rgba(120, 20, 30, 0.14); }

.venue-cover {
  position: relative; height: 84px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px; color: #fff;
}
.venue-cover::after {
  content: ''; position: absolute; inset: 0;
  background: repeating-linear-gradient(125deg, transparent 0 22px, rgba(255, 255, 255, 0.05) 22px 24px);
}
.venue-cover[data-theme="辛亥革命"] { background: linear-gradient(120deg, #8a1620, #c0392b); }
.venue-cover[data-theme="党史"] { background: linear-gradient(120deg, #6d1017, #a91f2e); }
.venue-cover[data-theme="工运"] { background: linear-gradient(120deg, #7a3b12, #b8860b); }
.venue-cover[data-theme="抗战"] { background: linear-gradient(120deg, #4a1520, #8a1620); }
.venue-cover[data-theme=""] { background: linear-gradient(120deg, var(--red-800), var(--red-600)); }
.cover-glyph { font-size: 26px; font-weight: 700; letter-spacing: 8px; text-shadow: 0 2px 8px rgba(0,0,0,0.25); }
.cover-duration { position: relative; z-index: 1; font-size: 12px; background: rgba(0, 0, 0, 0.22); padding: 3px 10px; border-radius: 999px; }

.venue-body { padding: 14px 18px 16px; display: flex; flex-direction: column; flex: 1; }
.venue-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.venue-head h3 { margin: 0; font-size: 16px; color: var(--red-800); }
.venue-addr { font-size: 12.5px; color: var(--ink-light); margin: 8px 0 4px; }
.venue-meta { font-size: 12px; color: var(--ink-light); margin: 0 0 12px; }
.venue-actions { margin-top: auto; display: flex; align-items: center; gap: 14px; }
.nav-link { font-size: 12.5px; color: var(--red-700); text-decoration: none; border-bottom: 1px dashed var(--red-600); }
.nav-link:hover { color: var(--red-900); }

/* ===== 导览：头部与进度 ===== */
.tour-head { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin-bottom: 16px; }
.back-btn { flex: none; }
.tour-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tour-title h2 { margin: 0; font-size: 19px; color: var(--red-800); }
.tour-progress { margin-left: auto; min-width: 220px; }
.progress-text { display: flex; justify-content: space-between; font-size: 12.5px; color: var(--ink-light); margin-bottom: 5px; }
.progress-text b { color: var(--red-700); }
.progress-bar { height: 8px; background: var(--red-100); border-radius: 999px; overflow: hidden; }
.progress-bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--red-700), var(--red-600)); border-radius: 999px; transition: width 0.35s; }

/* ===== 导览：主体两栏 ===== */
.tour-body { display: grid; grid-template-columns: 250px 1fr; gap: 16px; align-items: start; }
/* grid/flex 子项默认 min-width:auto，长内容会把卡片撑破出边距，必须显式归零 */
.point-card { min-width: 0; }

.tour-map { padding: 14px; position: sticky; top: 88px; }
.map-title { font-size: 13px; font-weight: 700; color: var(--red-800); margin-bottom: 10px; letter-spacing: 1px; }
.stop {
  display: flex; gap: 10px; width: 100%; text-align: left; background: none; border: none;
  border-radius: 10px; padding: 8px 10px; cursor: pointer; position: relative;
}
.stop + .stop::before {
  content: ''; position: absolute; left: 19px; top: -8px; height: 14px; width: 2px;
  background: var(--line); border-radius: 1px;
}
.stop:hover { background: var(--red-50); }
.stop.current { background: var(--red-50); box-shadow: inset 0 0 0 1.5px var(--red-600); }
.stop-dot {
  flex: none; width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: var(--ink-light);
  background: #fff; border: 2px solid var(--line); z-index: 1;
}
.stop.current .stop-dot { background: var(--red-700); border-color: var(--red-700); color: #fff; }
.stop.done .stop-dot { background: var(--gold); border-color: var(--gold); color: var(--red-900); }
.stop-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.stop-info b { font-size: 13px; color: var(--ink); }
.stop.current .stop-info b { color: var(--red-700); }
.stop-info em {
  font-style: normal; font-size: 11.5px; color: var(--ink-light);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px;
}

/* ===== 导览：点位卡片 ===== */
.point-card { display: flex; flex-direction: column; gap: 16px; }
.point-head { border-bottom: 1px dashed var(--line); padding-bottom: 12px; }
.point-no {
  display: inline-block; font-size: 12px; font-weight: 700; color: #fff;
  background: var(--red-700); border-radius: 6px; padding: 2px 10px; margin-bottom: 8px; letter-spacing: 1px;
}
.point-head h3 { margin: 0 0 6px; font-size: 20px; color: var(--red-800); }
.point-brief { margin: 0; font-size: 13px; color: var(--ink-light); }

.explain-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.explain-label { font-size: 12px; color: var(--ink-light); }
.btn.mini { padding: 4px 12px; font-size: 12px; }

.sources { margin-top: 12px; border-top: 1px dashed var(--line); padding-top: 8px; }
.sources-title { font-size: 12px; color: var(--ink-light); margin-bottom: 6px; }
.source-item { border: 1px solid var(--line); border-radius: 8px; margin: 6px 0; overflow: hidden; }
.source-item.flash { border-color: var(--red-600); box-shadow: 0 0 0 2px rgba(192, 57, 43, 0.18); }
.source-head {
  display: flex; align-items: baseline; gap: 6px; width: 100%; background: none; border: none;
  padding: 6px 8px; cursor: pointer; text-align: left; font-size: 12px; color: var(--ink-light);
}
.source-head:disabled { cursor: default; }
.source-head .tag:first-child { background: var(--red-700); color: #fff; }
.source-snippet { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chevron { flex: none; font-size: 10px; }
.source-full {
  margin: 0 6px 6px; padding: 8px 10px; background: var(--red-50); border-radius: 6px;
  font-size: 12.5px; line-height: 1.75; color: var(--ink); white-space: pre-wrap;
  word-break: break-word; max-height: 220px; overflow-y: auto;
}

/* ===== 随行问答 ===== */
.qa-box {
  border: 1px solid var(--line); border-radius: 12px; background: var(--red-50); padding: 12px 14px;
}
.qa-title { font-size: 12.5px; color: var(--red-800); font-weight: 700; margin-bottom: 8px; }
.qa-msgs { display: flex; flex-direction: column; gap: 10px; margin-bottom: 10px; max-height: 340px; overflow-y: auto; }
.qa-msg { display: flex; }
.qa-msg.user { justify-content: flex-end; }
.qa-bubble {
  max-width: 86%; background: #fff; border: 1px solid var(--line);
  border-radius: 10px; padding: 8px 12px; font-size: 13.5px;
}
.qa-msg.user .qa-bubble { background: var(--red-700); color: #fff; border-color: var(--red-700); }
.qa-msg.user .qa-bubble :deep(.md-body) { color: #fff; }
.qa-input { display: flex; gap: 8px; }
.qa-input input {
  flex: 1; border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px;
  font-size: 13.5px; outline: none; background: #fff;
}
.qa-input input:focus { border-color: var(--red-600); }

/* ===== 底部导航 ===== */
.point-foot { display: flex; align-items: center; gap: 10px; border-top: 1px dashed var(--line); padding-top: 14px; flex-wrap: wrap; }
.next-btn { margin-left: auto; }
.check-btn {
  border: 1.5px dashed var(--red-600); background: #fff; color: var(--red-700);
  border-radius: 10px; padding: 8px 18px; font-size: 13.5px; cursor: pointer; transition: all 0.15s;
}
.check-btn:hover { background: var(--red-50); }
.check-btn.done { border-style: solid; background: var(--gold); border-color: var(--gold); color: var(--red-900); font-weight: 700; }
.finish-btn { background: linear-gradient(120deg, var(--red-800), var(--red-600)); }

/* ===== 导览完成 ===== */
.tour-done { text-align: center; padding: 40px 20px; }
.done-badge {
  width: 64px; height: 64px; margin: 0 auto 14px; border-radius: 50%;
  background: var(--gold); color: var(--red-900); font-size: 30px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 18px rgba(184, 134, 11, 0.35);
}
.tour-done h3 { margin: 0 0 8px; color: var(--red-800); font-size: 19px; }
.tour-done p { color: var(--ink-light); font-size: 13.5px; line-height: 1.9; max-width: 420px; margin: 0 auto 18px; }
.tour-done p b { color: var(--red-700); font-size: 16px; }
.done-actions { display: flex; justify-content: center; gap: 12px; }

.loading-row { display: flex; align-items: center; gap: 10px; color: var(--ink-light); font-size: 13.5px; }
.err { color: #b03030; font-size: 13px; }

/* ===== 响应式 ===== */
@media (max-width: 900px) {
  .tour-body { grid-template-columns: 1fr; }
  .tour-map { position: static; display: flex; gap: 6px; overflow-x: auto; padding: 10px; }
  .map-title { display: none; }
  .stop { flex: none; width: auto; max-width: 180px; flex-direction: column; align-items: center; text-align: center; gap: 4px; padding: 8px; }
  .stop + .stop::before { left: -8px; top: 18px; height: 2px; width: 10px; }
  .stop-info em { max-width: 150px; white-space: normal; }
  .tour-progress { width: 100%; }
}
</style>
