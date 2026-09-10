<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Profile } from '~/types/api'

const theme = ref<'light' | 'dark' | 'system'>('system')
const { plain, togglePlain, restorePlain } = useGlossary()

// Same shared key as `useUnits`, so this costs no extra request.
const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })

onMounted(() => {
  const stored = localStorage.getItem('hevy-coach-theme')
  if (stored === 'light' || stored === 'dark') applyTheme(stored)
  // Read after mount, not during setup: the server has no localStorage, and
  // deciding the wording during render would make the two disagree.
  restorePlain()
})

function applyTheme(next: 'light' | 'dark' | 'system') {
  theme.value = next
  const root = document.documentElement
  if (next === 'system') {
    root.removeAttribute('data-theme')
    localStorage.removeItem('hevy-coach-theme')
  } else {
    root.setAttribute('data-theme', next)
    localStorage.setItem('hevy-coach-theme', next)
  }
}

function cycleTheme() {
  applyTheme(theme.value === 'light' ? 'dark' : theme.value === 'dark' ? 'system' : 'light')
}

/** The Total page is only meaningful for a goal judged on a total, so it is
 *  offered only then - a hypertrophy log has no main lifts to add up. */
const links = computed(() => [
  { to: '/', label: 'Dashboard' },
  { to: '/next', label: 'Next session' },
  ...(profile.value?.tracks_total ? [{ to: '/total', label: 'Total' }] : []),
  { to: '/workouts', label: 'Workouts' },
  { to: '/strength', label: 'Strength' },
  { to: '/exercises', label: 'Exercises' },
  { to: '/coach', label: 'Coach' },
  { to: '/settings', label: 'Settings' },
])
</script>

<template>
  <div>
    <header class="topbar">
      <div class="shell bar-inner">
        <NuxtLink to="/" class="brand">Hevy&nbsp;Coach</NuxtLink>
        <nav>
          <NuxtLink v-for="link in links" :key="link.to" :to="link.to" class="nav-link">
            {{ link.label }}
          </NuxtLink>
        </nav>
        <button
          class="btn toggle"
          type="button"
          :title="plain
            ? 'Switch to the technical names for each number'
            : 'Rename every number in plain English'"
          :aria-pressed="plain"
          @click="togglePlain"
        >
          {{ plain ? 'Plain' : 'Technical' }}
        </button>
        <button class="btn toggle" type="button" @click="cycleTheme">
          {{ theme === 'system' ? 'Auto' : theme === 'dark' ? 'Dark' : 'Light' }}
        </button>
      </div>
    </header>

    <main class="shell">
      <NuxtPage />
    </main>
  </div>
</template>

<style scoped>
.topbar {
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
  position: sticky;
  top: 0;
  z-index: 20;
}

.bar-inner {
  display: flex;
  align-items: center;
  gap: 20px;
  padding-top: 12px;
  padding-bottom: 12px;
}

.brand {
  font-weight: 600;
  text-decoration: none;
  letter-spacing: -0.01em;
}

nav {
  display: flex;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
}

.nav-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  padding: 5px 10px;
  border-radius: 7px;
  white-space: nowrap;
}

.nav-link:hover {
  color: var(--text-primary);
}

.nav-link.router-link-active {
  color: var(--text-primary);
  background: var(--page);
  font-weight: 500;
}

.toggle {
  flex: none;
}

main {
  padding-top: 24px;
}
</style>
