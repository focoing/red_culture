// API 客户端：普通请求用 axios，流式接口（问答/导览讲解）用 fetch+SSE 解析
import axios from 'axios'

// ================= 登录态（localStorage 持久化） =================
const TOKEN_KEY = 'rc_token'
const USER_KEY = 'rc_user'

export function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }

export function getUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function setAuth(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

const http = axios.create({ baseURL: '/api', timeout: 120000 })

// 请求拦截：自动附加登录令牌
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：登录过期（401）时清除本地态并广播全局事件，由 App.vue 弹出登录框
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    // 登录/注册接口自身的 401（如密码错误）不算"登录过期"，不触发全局流程
    const url = (error.config && error.config.url) || ''
    const fromAuthApi = url.includes('/auth/login') || url.includes('/auth/register')
    if (error.response && error.response.status === 401 && !fromAuthApi) {
      clearAuth()
      window.dispatchEvent(new CustomEvent('rc:unauthorized'))
    }
    return Promise.reject(error)
  },
)

// ================= 认证接口 =================
export async function register({ username, password, grade }) {
  const { data } = await http.post('/auth/register', { username, password, grade })
  setAuth(data.token, data.user)
  return data
}

export async function login({ username, password }) {
  const { data } = await http.post('/auth/login', { username, password })
  setAuth(data.token, data.user)
  return data
}

export async function fetchMe() {
  const { data } = await http.get('/auth/me')
  if (data && data.user) localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  return data.user
}

export function logout() { clearAuth() }

// 提取后端错误文案：优先 response.data.detail（含 401 未登录 / 429 限流提示）
export function apiErrMsg(e, fallback = '请求失败，请稍后再试') {
  const detail = e && e.response && e.response.data && e.response.data.detail
  return detail || (e && e.message) || fallback
}

// 将流式请求错误转为用户可读文案：
// - 被主动中断（AbortError，组件卸载/换页）返回 ''，调用方无需提示
// - 401/429 等带 detail 的错误直接展示后端文案，429 时补充 Retry-After 秒数
// - 其余视为连接失败，展示 fallback 提示
export function streamErrMsg(e, fallback = '无法连接服务') {
  if (e && e.name === 'AbortError') return ''
  if (e && e.detail) {
    const sec = e.retryAfter && !String(e.detail).includes(String(e.retryAfter))
      ? `（请 ${e.retryAfter} 秒后再试）`
      : ''
    return `${e.detail}${sec}`
  }
  return `${fallback}：${(e && e.message) || '网络异常'}`
}

// ================= 普通业务接口 =================
export const getHealth = () => http.get('/health')
export const getVenues = () => http.get('/venues')
export const getVenueDetail = (name) => http.get(`/venues/${encodeURIComponent(name)}/detail`)
export const getGrades = () => http.get('/grades')
export const generateRoute = (payload) => http.post('/route', payload)
export const generateTasks = (payload) => http.post('/tasks', payload)

// ---- 场馆导览 ----
export const getTourRoute = (name) => http.get(`/tour/${encodeURIComponent(name)}/route`)
export const getTransitPlan = (venues) => http.post('/route/transit', { venues })

/**
 * 通用 SSE 流式请求：解析 event: xxx\ndata: yyy 帧，回调 (type, data)。
 * @param {string}      url     完整 URL
 * @param {object}      payload JSON 请求体
 * @param {function}    onEvent 回调 (type, data) -> void
 * @param {AbortSignal} [signal] 可选中断信号（组件卸载时中断流）
 */
async function sseStream(url, payload, onEvent, signal) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal,
  })

  if (!resp.ok) {
    // 非 200：尝试读取 JSON 错误体（401 未登录 / 429 限流等），把后端 detail 抛给调用方
    let detail = ''
    try {
      const body = await resp.json()
      detail = (body && body.detail) || ''
    } catch { /* 响应体不是 JSON */ }
    let retryAfter = 0
    if (resp.status === 429) {
      const n = parseInt(resp.headers.get('Retry-After'), 10)
      if (Number.isFinite(n)) retryAfter = n
    }
    if (resp.status === 401) {
      clearAuth()
      window.dispatchEvent(new CustomEvent('rc:unauthorized'))
    }
    const err = new Error(detail || `请求失败：${resp.status}`)
    err.status = resp.status
    err.detail = detail
    if (retryAfter) err.retryAfter = retryAfter
    throw err
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 解析 SSE 帧：event: xxx\ndata: yyy\n\n
    const frames = buffer.split('\n\n')
    buffer = frames.pop()
    for (const frame of frames) {
      let type = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) type = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) {
        try { onEvent(type, JSON.parse(data)) } catch { onEvent(type, data) }
      }
    }
  }
}

/**
 * 流式问答（SSE）。
 * @param {object}      payload  {question, grade, session_id, venue, section}
 * @param {function}    onEvent  回调 (type, data) -> void
 * @param {AbortSignal} [signal] 可选中断信号
 */
export async function chatStream(payload, onEvent, signal) {
  return sseStream('/api/chat/stream', payload, onEvent, signal)
}

/**
 * 点位导览讲解词（SSE 流式）。
 * @param {object}      payload  {venue, section, grade}
 * @param {function}    onEvent  回调 (type, data) -> void（sources/delta/done/error）
 * @param {AbortSignal} [signal] 可选中断信号
 */
export async function tourExplainStream(payload, onEvent, signal) {
  return sseStream('/api/tour/explain', payload, onEvent, signal)
}
