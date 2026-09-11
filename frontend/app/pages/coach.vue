<script setup lang="ts">
/**
 * Chat with the coach. It answers by querying the training database directly.
 *
 * The model runs in one of two places and the page has to say which: with an
 * ANTHROPIC_API_KEY it goes to the Anthropic API, and without one it runs on
 * the Claude Code CLI installed on this machine, which authenticates as its
 * own login. `GET /api/coach` is asked before the user types so a machine with
 * neither says so up front instead of swallowing the first question.
 */
import { computed, nextTick, ref } from 'vue'
import type { CoachAnswer, CoachStatus } from '~/types/api'

type Turn = {
  role: 'user' | 'coach'
  text: string
  /** Where the answer came from, in the reader's terms. */
  note?: string
  failed?: boolean
}

const { data: status } = await useFetch<CoachStatus>('/api/coach')

const turns = ref<Turn[]>([])
const question = ref('')
const busy = ref(false)
const thread = ref<HTMLElement | null>(null)

/** The CLI backend keeps the transcript on its own side; this is the handle to
 *  it, so a follow-up question lands in the same conversation. The API backend
 *  returns nothing here and each question stands alone. */
const session = ref<string | null>(null)

const ready = computed(() => status.value?.ready ?? false)

/** Where the answers come from, in the user's terms rather than the flag's. */
const source = computed(() => {
  if (status.value?.backend === 'cli') {
    return `Running on the Claude Code CLI on this machine (${status.value.model}) - no API key needed.`
  }
  if (status.value?.backend === 'api') {
    return `Running on the Anthropic API (${status.value.model}).`
  }
  return ''
})

/** How the answer was reached. Worth saying: a computed answer is a lookup the
 *  app did itself, and a cached one is the same answer as last time by
 *  definition - neither is the coach having a fresh thought. */
function provenance(result: CoachAnswer): string {
  const what = [...new Set(result.tools_used)].join(', ')
  if (result.backend === 'computed') {
    return `Computed from your log - ${what}. No model involved.`
  }
  const queried = what ? `Queried: ${what}` : 'Answered from the briefing, no extra queries'
  return result.cached
    ? `Same answer as last time - your log has not changed. ${queried}`
    : queried
}

const SUGGESTIONS = [
  'What should I change in my training this month?',
  'Which lift is furthest behind the standards, and how do I fix it?',
  'Is my volume distribution balanced?',
  'Am I progressing on bench press, and what should I do next?',
]

async function ask(text?: string) {
  const prompt = (text ?? question.value).trim()
  if (!prompt || busy.value || !ready.value) return

  turns.value.push({ role: 'user', text: prompt })
  question.value = ''
  busy.value = true
  await scrollDown()

  try {
    const result = await $fetch<CoachAnswer>('/api/coach', {
      method: 'POST',
      body: { question: prompt, session_id: session.value },
    })
    session.value = result.session_id ?? null
    turns.value.push({
      role: 'coach',
      text: result.answer || 'No answer returned.',
      note: provenance(result),
    })
  } catch (error: unknown) {
    const detail = (error as { data?: { detail?: string } })?.data?.detail
    turns.value.push({
      role: 'coach',
      failed: true,
      text: detail || 'The coach could not be reached. Is the backend running?',
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
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
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
  <div class="flex min-h-[calc(100vh-208px)] flex-col">
    <div class="mb-4 flex flex-wrap items-baseline gap-3">
      <h1>Coach</h1>
      <p class="text-muted-foreground m-0 text-[13px]">
        Answers come from querying your actual training log.
      </p>
    </div>

    <!-- The scroller is the inner div, not the Card: `thread` has to be a real
         element for `scrollTo`, and a component ref is an instance. -->
    <Card class="flex-1 overflow-hidden py-0">
      <div ref="thread" class="flex max-h-[calc(100vh-308px)] flex-col gap-3.5 overflow-y-auto p-5">
        <div v-if="turns.length === 0" class="m-auto max-w-[460px] text-center">
          <Alert v-if="!ready" variant="destructive" class="text-left">
            <AlertTitle>The coach has no model to run on</AlertTitle>
            <AlertDescription>
              {{ status?.detail }}
            </AlertDescription>
          </Alert>
          <template v-else>
            <p class="text-muted-foreground">Ask about progression, programming, or where you stand.</p>
            <div class="mt-4 flex flex-col gap-2">
              <Button
                v-for="suggestion in SUGGESTIONS"
                :key="suggestion"
                variant="outline"
                class="h-auto justify-start py-2 text-left whitespace-normal"
                @click="ask(suggestion)"
              >
                {{ suggestion }}
              </Button>
            </div>
          </template>
        </div>

        <div
          v-for="(turn, i) in turns"
          :key="i"
          class="flex"
          :class="turn.role === 'user' ? 'justify-end' : ''"
        >
          <div
            class="max-w-[76%] rounded-xl px-3.5 py-3 text-[13px]"
            :class="[
              turn.role === 'user'
                ? 'bg-primary text-primary-foreground'
                : 'bg-background border',
              turn.failed && 'border-critical',
            ]"
          >
            <div
              v-if="turn.role === 'coach'"
              class="[&_code]:bg-card [&_li]:mb-1 [&_p:last-child]:mb-0 [&_p]:mb-2.5
                     [&_code]:rounded [&_code]:px-1.5 [&_code]:py-px [&_code]:text-xs
                     [&_ul]:mb-2.5 [&_ul]:list-disc [&_ul]:pl-[18px]"
              v-html="render(turn.text)"
            />
            <p v-else class="m-0">{{ turn.text }}</p>
            <p v-if="turn.note" class="text-subtle mt-2.5 mb-0 text-[11px]">{{ turn.note }}</p>
          </div>
        </div>

        <div v-if="busy" class="flex">
          <div class="bg-background text-muted-foreground max-w-[76%] rounded-xl border px-3.5 py-3 text-[13px]">
            Reading your training log...
          </div>
        </div>
      </div>
    </Card>

    <form class="mt-3.5 flex gap-2" @submit.prevent="ask()">
      <Input
        v-model="question"
        type="text"
        class="h-10 flex-1 text-[13px]"
        placeholder="Ask about your training..."
        :disabled="busy || !ready"
      />
      <Button type="submit" class="h-10" :disabled="busy || !ready || !question.trim()">Ask</Button>
    </form>
    <p v-if="source" class="text-subtle mt-2 mb-0 text-[11px]">{{ source }}</p>
  </div>
</template>
