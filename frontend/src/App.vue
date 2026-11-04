<script setup>
import { ref, reactive, provide, onMounted, onUnmounted } from 'vue'
import GradeSelector from './components/GradeSelector.vue'
import ChatPanel from './components/ChatPanel.vue'
import TourPanel from './components/TourPanel.vue'
import StudyTools from './components/StudyTools.vue'
import { login, register, logout as apiLogout, getUser, apiErrMsg } from './api'

const grade = ref('primary_high') // 全局学段状态
provide('grade', grade)

// 导览为主：场馆导览（默认首页）-> 研学工具 -> 史料问答（随行辅助）
const tab = ref('tour')
const tabs = [
  { key: 'tour', label: '场馆导览' },
  { key: 'tools', label: '研学工具' },
  { key: 'chat', label: '史料问答' },
]

// ================= 登录 / 注册 =================
const GRADE_KEYS = ['primary_low', 'primary_high', 'junior', 'senior']
const user = ref(getUser())
const authOpen = ref(false)
const mode = ref('login') // login | register
const authBusy = ref(false)
const authError = ref('')
const form = reactive({ username: '', password: '', grade: 'primary_high' })

function openAuth(m = 'login') {
  mode.value = m
  authError.value = ''
  authOpen.value = true
}
function closeAuth() { if (!authBusy.value) authOpen.value = false }
function switchMode(m) { mode.value = m; authError.value = '' }

async function submitAuth() {
  if (authBusy.value) return
  const username = form.username.trim()
  if (!username || !form.password) { authError.value = '请填写用户名和密码'; return }
  authBusy.value = true
  authError.value = ''
  try {
    const data = mode.value === 'login'
      ? await login({ username, password: form.password })
      : await register({ username, password: form.password, grade: form.grade })
    user.value = data.user
    // 同步账号学段到全局学段（讲解风格随之切换）
    if (data.user && GRADE_KEYS.includes(data.user.grade)) grade.value = data.user.grade
    authOpen.value = false
    form.password = ''
  } catch (e) {
    authError.value = apiErrMsg(e, mode.value === 'login' ? '登录失败，请稍后再试' : '注册失败，请稍后再试')
  } finally {
    authBusy.value = false
  }
}

function doLogout() {
  apiLogout()
  user.value = null
}

// 登录过期（任意接口返回 401）时自动弹出登录框
const onUnauthorized = () => openAuth('login')
onMounted(() => window.addEventListener('rc:unauthorized', onUnauthorized))
onUnmounted(() => window.removeEventListener('rc:unauthorized', onUnauthorized))
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
      <template v-if="user">
        <span class="user-chip" :title="user.username">{{ user.username }}</span>
        <button class="auth-btn" @click="doLogout">退出</button>
      </template>
      <button v-else class="auth-btn gold" @click="openAuth('login')">登录 / 注册</button>
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
      <!-- 学段选择：跟随页签行展示，三个页面均可直接切换 -->
      <div class="tab-grade">
        <span class="grade-label">学段</span>
        <GradeSelector v-model="grade" />
      </div>
    </nav>

    <TourPanel v-show="tab === 'tour'" />
    <StudyTools v-show="tab === 'tools'" />
    <ChatPanel v-show="tab === 'chat'" />
  </main>

  <!-- 登录/注册弹窗 -->
  <teleport to="body">
    <div v-if="authOpen" class="auth-mask" @click.self="closeAuth">
      <div class="auth-modal card">
        <div class="auth-head">
          <h2 class="section-title">{{ mode === 'login' ? '欢迎回来' : '建立你的小档案' }}</h2>
          <button class="auth-close" aria-label="关闭" @click="closeAuth">✕</button>
        </div>
        <div class="auth-tabs">
          <button class="tab-btn" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
          <button class="tab-btn" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
        </div>
        <form class="auth-form" @submit.prevent="submitAuth">
          <input v-model.trim="form.username" placeholder="用户名" autocomplete="username" required />
          <input
            v-model="form.password" type="password" placeholder="密码"
            autocomplete="current-password" required
          />
          <select v-if="mode === 'register'" v-model="form.grade" aria-label="选择学段">
            <option value="primary_low">小学低年级（1-3 年级 · 故事化讲解）</option>
            <option value="primary_high">小学高年级（4-6 年级 · 通俗+小任务）</option>
            <option value="junior">初中（讲清脉络与因果）</option>
            <option value="senior">高中（深度分析+思辨）</option>
          </select>
          <div v-if="authError" class="auth-err">{{ authError }}</div>
          <button class="btn" type="submit" :disabled="authBusy">
            {{ authBusy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
/* ---------- 顶栏登录入口 ---------- */
.auth-btn {
  border: 1px solid rgba(255, 255, 255, 0.5);
  background: transparent;
  color: #fff;
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s;
}
.auth-btn:hover { background: rgba(255, 255, 255, 0.15); }
.auth-btn.gold { background: var(--gold); border-color: var(--gold); color: var(--red-900); font-weight: 700; }
.auth-btn.gold:hover { filter: brightness(1.06); }
.user-chip {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 13px;
}

/* ---------- 登录/注册弹窗 ---------- */
.auth-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(43, 34, 36, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.auth-modal { width: 340px; max-width: 100%; padding: 20px 22px; }
.auth-head { display: flex; align-items: center; justify-content: space-between; }
.auth-head .section-title { margin: 0; }
.auth-close {
  border: none;
  background: none;
  color: var(--ink-light);
  font-size: 15px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
}
.auth-close:hover { background: var(--red-50); color: var(--red-700); }
.auth-tabs { display: flex; gap: 8px; margin: 12px 0 14px; }
.auth-form { display: flex; flex-direction: column; gap: 12px; }
.auth-form input, .auth-form select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  outline: none;
  background: #fff;
  font-family: inherit;
}
.auth-form input:focus, .auth-form select:focus { border-color: var(--red-600); }
.auth-err { color: #b03030; font-size: 13px; }
</style>
