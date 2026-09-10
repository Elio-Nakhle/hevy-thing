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
            <p v-if="turn.tools?.length" class="text-subtle mt-2.5 mb-0 text-[11px]">
              Queried: {{ turn.tools.join(', ') }}
            </p>
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
        :disabled="busy"
      />
      <Button type="submit" class="h-10" :disabled="busy || !question.trim()">Ask</Button>
    </form>
  </div>
</template>
