<script setup lang="ts">
/** Chat with the coach. It answers by querying the training database directly. */
import { nextTick, ref } from 'vue'

type Turn = {
  role: 'user' | 'coach'
  text: string
  tools?: string[]
  failed?: boolean
}

const turns = ref<Turn[]>([])
const question = ref('')
const busy = ref(false)
const thread = ref<HTMLElement | null>(null)

const SUGGESTIONS = [
  'What should I change in my training this month?',
  'Which lift is furthest behind the standards, and how do I fix it?',
  'Is my volume distribution balanced?',
  'Am I progressing on bench press, and what should I do next?',
]

async function ask(text?: string) {
  const prompt = (text ?? question.value).trim()
  if (!prompt || busy.value) return

  turns.value.push({ role: 'user', text: prompt })
  question.value = ''
  busy.value = true
  await scrollDown()

  try {
    const result = await $fetch<{ answer: string; tools_used: string[] }>('/api/coach', {
      method: 'POST',
      body: { question: prompt },
    })
    turns.value.push({
      role: 'coach',
      text: result.answer || 'No answer returned.',
      tools: [...new Set(result.tools_used)],
    })
  } catch (error: unknown) {
    const detail = (error as { data?: { detail?: string } })?.data?.detail
    turns.value.push({
      role: 'coach',
      failed: true,
      text: detail || 'The coach could not be reached. Is ANTHROPIC_API_KEY set?',
    })
  } finally {
    busy.value = false
    await scrollDown()
  }
}

async function scrollDown() {
  await nextTick()
  thread.value?.scrollTo({ top: thread.value.scrollHeight, behavior: 'smooth' })
}

/** Minimal markdown: paragraphs, bullets, bold. The coach is told to keep it simple. */
function render(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')

  return escaped
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split('\n')
      if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
        const items = lines.map((line) => `<li>${line.replace(/^\s*[-*]\s+/, '')}</li>`).join('')
        return `<ul>${items}</ul>`
      }
      return `<p>${lines.join('<br>')}</p>`
    })
    .join('')
}
</script>

<template>
  <div class="coach">
    <div class="page-head">
      <h1>Coach</h1>
      <p class="secondary">Answers come from querying your actual training log.</p>
    </div>

    <div ref="thread" class="thread card">
      <div v-if="turns.length === 0" class="intro">
        <p class="secondary">Ask about progression, programming, or where you stand.</p>
        <div class="suggestions">
          <button
            v-for="suggestion in SUGGESTIONS"
            :key="suggestion"
            class="btn"
            type="button"
            @click="ask(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>

      <div v-for="(turn, i) in turns" :key="i" class="turn" :class="turn.role">
        <div class="bubble" :class="{ failed: turn.failed }">
          <div v-if="turn.role === 'coach'" class="prose" v-html="render(turn.text)" />
          <p v-else class="user-text">{{ turn.text }}</p>
          <p v-if="turn.tools?.length" class="tools muted">
            Queried: {{ turn.tools.join(', ') }}
          </p>
        </div>
      </div>

      <div v-if="busy" class="turn coach">
        <div class="bubble secondary">Reading your training log...</div>
      </div>
    </div>

    <form class="composer" @submit.prevent="ask()">
      <input
        v-model="question"
        type="text"
        placeholder="Ask about your training..."
        :disabled="busy"
      />
      <button class="btn btn-primary" type="submit" :disabled="busy || !question.trim()">
        Ask
      </button>
    </form>
  </div>
</template>

<style scoped>
.coach {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 160px);
}

.page-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.page-head p {
  margin: 0;
  font-size: 13px;
}

.thread {
  flex: 1;
  overflow-y: auto;
  max-height: calc(100vh - 260px);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
}

.intro {
  margin: auto;
  text-align: center;
  max-width: 460px;
}

.suggestions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
}

.suggestions .btn {
  text-align: left;
}

.turn {
  display: flex;
}

.turn.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 76%;
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 13px;
}

.turn.user .bubble {
  background: var(--series-1);
  color: #fff;
}

.turn.coach .bubble {
  background: var(--page);
  border: 1px solid var(--border);
}

.bubble.failed {
  border-color: var(--critical);
}

.user-text {
  margin: 0;
}

.prose :deep(p) {
  margin: 0 0 10px;
}

.prose :deep(p:last-child) {
  margin-bottom: 0;
}

.prose :deep(ul) {
  margin: 0 0 10px;
  padding-left: 18px;
}

.prose :deep(li) {
  margin-bottom: 4px;
}

.prose :deep(code) {
  background: var(--surface-1);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}

.tools {
  margin: 10px 0 0;
  font-size: 11px;
}

.composer {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.composer input {
  flex: 1;
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-primary);
  border-radius: 9px;
  padding: 10px 13px;
  font: inherit;
  font-size: 13px;
}

.composer input:focus {
  outline: 2px solid var(--series-1);
  outline-offset: -1px;
}
</style>
