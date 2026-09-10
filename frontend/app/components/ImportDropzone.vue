<script setup lang="ts">
/**
 * Import a Hevy CSV export: drop it here, pick it from a dialog, or fall back to
 * the newest export already sitting in the backend's workouts folder.
 *
 * The upload posts multipart to the same `POST /api/import` the folder path
 * uses, and the backend stores what it receives in `workouts/` either way - so
 * the browser and the CLI never disagree about which export is current.
 */
import { ref } from 'vue'
import type { ImportResult } from '~/types/api'

// Named rather than bare: `compact` is also an auto-imported number formatter
// from `utils/format`, and an unqualified `compact` in the template resolves to
// whichever the tooling picks first.
const props = defineProps<{
  /** One-row form for a page header. The default is the tall empty-state box. */
  compact?: boolean
  /** Export already in the workouts folder, from `/api/health`. */
  availableExport?: string | null
  /** Shown while idle in compact mode - usually the last file imported. */
  hint?: string | null
}>()

const emit = defineEmits<{ imported: [ImportResult] }>()

const picker = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const busy = ref(false)
const message = ref('')
const failed = ref(false)

/** POST the export - a file if one was chosen, otherwise the folder's newest. */
async function send(file?: File) {
  busy.value = true
  failed.value = false
  message.value = ''

  let body: FormData | undefined
  if (file) {
    body = new FormData()
    body.append('file', file)
  }

  try {
    const result = await $fetch<ImportResult>('/api/import', { method: 'POST', body })
    message.value = result.summary
    emit('imported', result)
  } catch (error: unknown) {
    const failure = error as { data?: { detail?: string }; statusCode?: number }
    failed.value = true
    // A 502 is the dev proxy telling us nothing is listening on the API port.
    message.value =
      failure?.data?.detail
      ?? (failure?.statusCode === 502
        ? 'Cannot reach the API - start it with `uv run hevy-coach serve`.'
        : 'Import failed.')
  } finally {
    busy.value = false
  }
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // Clear it, or choosing the same file twice fires no second change event.
  input.value = ''
  if (file) void send(file)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  // The backend checks this too; catching it here saves a round trip and can
  // name the file the user actually dropped.
  if (!file.name.toLowerCase().endsWith('.csv')) {
    failed.value = true
    message.value = `${file.name} is not a CSV. Export from Hevy: Settings → Export Data.`
    return
  }
  void send(file)
}
</script>

<template>
  <div
    class="transition-[border-color,background] duration-[120ms]"
    :class="[
      props.compact
        ? 'flex items-center gap-3 text-left'
        : 'border-baseline bg-card rounded-lg border border-dashed px-6 pt-10 pb-8 text-center',
      dragging && props.compact && 'ring-primary rounded-lg ring-2 ring-offset-6',
      dragging && !props.compact && 'border-primary border-solid bg-[color-mix(in_srgb,var(--series-1)_7%,var(--surface-1))]',
      /* While a file is over the box, let the drag through the contents - a
         child swallowing dragleave is what makes drop zones flicker. */
      dragging && '[&>*:not(input)]:pointer-events-none',
    ]"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <!-- Kept in the DOM rather than rebuilt per click, so `picker` is always there. -->
    <input
      ref="picker"
      class="hidden"
      type="file"
      accept=".csv,text/csv"
      @change="onPick"
    >

    <template v-if="props.compact">
      <span v-if="message" class="text-xs" :class="failed ? 'text-critical' : 'text-success'">
        {{ message }}
      </span>
      <span v-else-if="hint" class="text-muted-foreground text-xs">{{ hint }}</span>
      <Button
        size="sm"
        :disabled="busy"
        title="Upload a Hevy CSV export"
        @click="picker?.click()"
      >
        {{ busy ? 'Importing...' : 'Import CSV' }}
      </Button>
    </template>

    <template v-else>
      <h2>Import your training history</h2>
      <p class="text-muted-foreground mx-auto mt-2.5 max-w-[46ch] text-[13px]">
        In Hevy: <strong>Profile &rarr; Settings &rarr; Export Data</strong>. Drop the CSV it
        sends you anywhere in this box.
      </p>
      <Button class="mt-[18px]" :disabled="busy" @click="picker?.click()">
        {{ busy ? 'Importing...' : 'Choose a CSV file' }}
      </Button>

      <p
        v-if="message"
        class="mx-auto mt-4 max-w-[52ch] text-xs"
        :class="failed ? 'text-critical' : 'text-success'"
      >
        {{ message }}
      </p>

      <p class="mt-[18px] mb-0 text-xs">
        <Button
          v-if="availableExport"
          variant="link"
          size="sm"
          class="text-muted-foreground h-auto p-0 text-xs underline underline-offset-[3px]"
          :disabled="busy"
          @click="send()"
        >
          Or import {{ availableExport }} from the workouts folder
        </Button>
        <span v-else class="text-subtle">
          No export yet? Run
          <code class="bg-background rounded-[5px] px-1.5 py-0.5 text-xs">uv run hevy-coach demo</code>
          for a synthetic log.
        </span>
      </p>
    </template>
  </div>
</template>
