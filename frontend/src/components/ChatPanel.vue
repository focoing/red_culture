<script setup>
// 史料问答面板：游览途中遇到疑问时，查询红色史料与历史细节（流式 RAG 对话 + 检索来源展示）
import { nextTick, ref, inject } from 'vue'
import { chatStream } from '../api'
import MarkdownView from './MarkdownView.vue'

const grade = inject('grade')

const messages = ref([]) // {role, content, sources?, streaming?}
const input = ref('')
const sending = ref(false)
const sessionId = ref(null)
const listEl = ref(null)

const WELCOME = {
  role: 'assistant',
  content:
    '你好！这里是**武汉红色文化导览小助手**的史料查询工具 📚\n\n' +
    '逛场馆时遇到疑问，可在这里查询红色史料与历史细节。比如：\n\n' +
    '- 八七会议是在哪里召开的？\n- 中山舰为什么会沉在长江里？\n- 帮我讲讲二七大罢工\n\n' +
    '想让我带你逐站参观场馆，请回到「**场馆导览**」页。',
}

messages.value.push(WELCOME)

const SUGGESTIONS = [
  '八七会议为什么重要？',
  '中山舰上发生了什么故事？',
  '武昌起义的第一枪是谁打响的？',
  '为什么说武汉曾是"赤都"？',
]


function scrollBottom() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

async function send(text) {
  const question = (text || input.value).trim()
  if (!question || sending.value) return

  input.value = ''
  messages.value.push({ role: 'user', content: question })
  const reply = { role: 'assistant', content: '', sources: [], streaming: true }
  messages.value.push(reply)
  sending.value = true
  scrollBottom()

  try {
    await chatStream(
      { question, grade: grade.value, session_id: sessionId.value },
      (type, data) => {
        if (type === 'meta') sessionId.value = data.session_id
        else if (type === 'sources') reply.sources = data
        else if (type === 'delta') { reply.content += data; scrollBottom() }
        else if (type === 'tool') {
          const labels = { query_venue_info: '场馆参观信息', list_venues: '场馆目录', search_history: '史料库' }
          reply.toolHint = (data || []).map((t) => labels[t.name] || t.name).join('、')
        }
        else if (type === 'done') { reply.content = data; reply.streaming = false }
        else if (type === 'error') {
          reply.content += `\n\n> ⚠️ 出错了：${data.message || '服务异常'}`
          reply.streaming = false
        }
      },
    )
  } catch (e) {
    reply.content += `\n\n> ⚠️ 无法连接服务：${e.message}（请确认后端已启动且已配置智谱 API Key）`
  } finally {
    reply.streaming = false
    sending.value = false
    scrollBottom()
  }
}

function resetChat() {
  messages.value = [WELCOME]
  sessionId.value = null
}

// 点击引用角标 [n]：展开对应史料原文并高亮滚动到该条
function onCite(n, msg) {
  const s = msg.sources && msg.sources[n - 1]
  if (!s) return
  s._open = true
  const i = messages.value.indexOf(msg)
  nextTick(() => {
    const el = document.getElementById(`src-${i}-${n - 1}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    s._flash = true
    setTimeout(() => { s._flash = false }, 1600)
  })
}
</script>

<template>
  <div class="chat-layout card">
    <div class="chat-head">
      <h2 class="section-title">史料问答</h2>
      <button class="btn ghost" @click="resetChat">清空对话</button>
    </div>

    <div class="msg-list" ref="listEl">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === 'user' ? '我' : '旗' }}</div>
        <div class="bubble">
          <MarkdownView v-if="m.content" :content="m.content" @cite="(n) => onCite(n, m)" />
          <div v-if="m.streaming && m.toolHint && !m.content" class="tool-hint">🔍 正在查询{{ m.toolHint }}…</div>
          <div v-if="m.streaming" class="loading-dots"><i /><i /><i /></div>

          <div v-if="m.role === 'assistant' && m.sources && m.sources.length && !m.streaming" class="sources">
            <div class="sources-title">📚 参考史料 · 点击角标或条目查看原文</div>
            <div
              v-for="(s, j) in m.sources" :key="j"
              :id="`src-${i}-${j}`"
              class="source-item"
              :class="{ flash: s._flash }"
            >
              <button
                class="source-head"
                :disabled="!s.content"
                @click="s._open = !s._open"
              >
                <span class="tag">{{ j + 1 }}</span>
                <span class="tag">{{ s.venue }}</span>
                <span class="source-snippet">{{ (s.section ? s.section + ' · ' : '') + s.snippet }}…</span>
                <span v-if="s.content" class="chevron">{{ s._open ? '▲' : '▼' }}</span>
              </button>
              <div v-if="s._open && s.content" class="source-full">{{ s.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="suggestion-row">
      <button v-for="s in SUGGESTIONS" :key="s" class="suggestion" @click="send(s)">
        {{ s }}
      </button>
    </div>

    <div class="input-row">
      <input
        v-model="input"
        type="text"
        :disabled="sending"
        placeholder="输入想查询的史料问题，比如：毛泽东在武昌都府堤做了什么？"
        @keyup.enter="send()"
      />
      <button class="btn" :disabled="sending || !input.trim()" @click="send()">发送</button>
    </div>
  </div>
</template>

<style scoped>
.chat-layout { display: flex; flex-direction: column; height: calc(100vh - 210px); min-height: 520px; }
.chat-head { display: flex; justify-content: space-between; align-items: center; }
.chat-head .section-title { margin: 0; }

.msg-list { flex: 1; overflow-y: auto; padding: 14px 4px; display: flex; flex-direction: column; gap: 16px; }

.msg { display: flex; gap: 10px; }
.msg.user { flex-direction: row-reverse; }
.avatar {
  flex: none;
  width: 34px; height: 34px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700;
  background: var(--red-100); color: var(--red-700);
}
.msg.user .avatar { background: var(--gold); color: var(--red-900); }

.bubble {
  max-width: 76%;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 14px;
}
.msg.user .bubble { background: var(--red-700); color: #fff; border-color: var(--red-700); }
.msg.user .bubble :deep(.md-body) { color: #fff; }

.sources { margin-top: 10px; border-top: 1px dashed var(--line); padding-top: 8px; }
.sources-title { font-size: 12px; color: var(--ink-light); margin-bottom: 6px; }
.source-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  margin: 6px 0;
  overflow: hidden;
}
.source-item.flash { border-color: var(--red-600); box-shadow: 0 0 0 2px rgba(192, 57, 43, 0.18); }
.source-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: 100%;
  background: none;
  border: none;
  padding: 6px 8px;
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  color: var(--ink-light);
}
.source-head:disabled { cursor: default; }
.source-head .tag { flex: none; }
.source-head .tag:first-child { background: var(--red-700); color: #fff; }
.source-snippet { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chevron { flex: none; font-size: 10px; }
.source-full {
  margin: 0 6px 6px;
  padding: 8px 10px;
  background: var(--red-50);
  border-radius: 6px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}

.tool-hint { font-size: 12.5px; color: var(--ink-light); margin-top: 4px; }
.suggestion-row { display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 0 6px; }
.suggestion {
  border: 1px dashed var(--red-600);
  background: var(--red-50);
  color: var(--red-800);
  border-radius: 999px;
  font-size: 12.5px;
  padding: 5px 14px;
  cursor: pointer;
}
.suggestion:hover { background: var(--red-100); }

.input-row { display: flex; gap: 10px; padding-top: 8px; border-top: 1px solid var(--line); }
.input-row input {
  flex: 1;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  outline: none;
}
.input-row input:focus { border-color: var(--red-600); }
</style>
