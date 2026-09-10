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

defineProps<{
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
    class="dz"
    :class="{ compact, over: dragging }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <input
      ref="picker"
      class="file-input"
      type="file"
      accept=".csv,text/csv"
      @change="onPick"
    >

    <template v-if="compact">
      <span v-if="message" class="msg" :class="{ bad: failed }">{{ message }}</span>
      <span v-else-if="hint" class="msg secondary">{{ hint }}</span>
      <button
        class="btn btn-primary"
        type="button"
        :disabled="busy"
        title="Upload a Hevy CSV export"
        @click="picker?.click()"
      >
        {{ busy ? 'Importing...' : 'Import CSV' }}
      </button>
    </template>

    <template v-else>
      <h2>Import your training history</h2>
      <p class="lede secondary">
        In Hevy: <strong>Profile &rarr; Settings &rarr; Export Data</strong>. Drop the CSV it
        sends you anywhere in this box.
      </p>
      <button
        class="btn btn-primary choose"
        type="button"
        :disabled="busy"
        @click="picker?.click()"
      >
        {{ busy ? 'Importing...' : 'Choose a CSV file' }}
      </button>

      <p v-if="message" class="msg block" :class="{ bad: failed }">{{ message }}</p>

      <p class="alt">
        <button
          v-if="availableExport"
          class="link-quiet"
          type="button"
          :disabled="busy"
          @click="send()"
        >
          Or import {{ availableExport }} from the workouts folder
        </button>
        <span v-else class="muted">
          No export yet? Run <code>uv run hevy-coach demo</code> for a synthetic log.
        </span>
      </p>
    </template>
  </div>
</template>

<style scoped>
.dz {
  border: 1px dashed var(--baseline);
  border-radius: var(--radius);
  background: var(--surface-1);
  padding: 40px 24px 32px;
  text-align: center;
  transition: border-color 120ms ease, background 120ms ease;
}

.dz.over {
  border-color: var(--series-1);
  border-style: solid;
  background: color-mix(in srgb, var(--series-1) 7%, var(--surface-1));
}

/* While a file is over the box, let the drag through the contents - a child
 * swallowing dragleave is what makes drop zones flicker. */
.dz.over > *:not(.file-input) {
  pointer-events: none;
}

.dz.compact {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
}

.dz.compact.over {
  outline: 2px solid var(--series-1);
  outline-offset: 6px;
  border-radius: 8px;
  background: none;
}

/* Kept in the DOM rather than rebuilt per click, so `picker` is always there. */
.file-input {
  display: none;
}

.lede {
  margin: 10px auto 0;
  max-width: 46ch;
  font-size: 13px;
}

.choose {
  margin-top: 18px;
  padding: 8px 16px;
  font-size: 13px;
}

.msg {
  font-size: 12px;
}

.msg.block {
  margin: 16px auto 0;
  max-width: 52ch;
  color: var(--success-text);
}

.msg.bad {
  color: var(--critical);
}

.alt {
  margin: 18px 0 0;
  font-size: 12px;
}

code {
  font-size: 12px;
  background: var(--page);
  padding: 2px 6px;
  border-radius: 5px;
}
</style>
