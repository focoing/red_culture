// API 客户端：普通请求用 axios，流式接口（问答/导览讲解）用 fetch+SSE 解析
import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

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
 */
async function sseStream(url, payload, onEvent) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!resp.ok) throw new Error(`请求失败：${resp.status}`)

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
 * @param {object}   payload  {question, grade, session_id, venue, section}
 * @param {function} onEvent  回调 (type, data) -> void
 */
export async function chatStream(payload, onEvent) {
  return sseStream('/api/chat/stream', payload, onEvent)
}

/**
 * 点位导览讲解词（SSE 流式）。
 * @param {object}   payload  {venue, section, grade}
 * @param {function} onEvent  回调 (type, data) -> void（sources/delta/done/error）
 */
export async function tourExplainStream(payload, onEvent) {
  return sseStream('/api/tour/explain', payload, onEvent)
}
