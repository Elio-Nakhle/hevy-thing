<script setup lang="ts">
import { onMounted, ref } from 'vue'

const theme = ref<'light' | 'dark' | 'system'>('system')

onMounted(() => {
  const stored = localStorage.getItem('hevy-coach-theme')
  if (stored === 'light' || stored === 'dark') applyTheme(stored)
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

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/strength', label: 'Strength' },
  { to: '/exercises', label: 'Exercises' },
  { to: '/coach', label: 'Coach' },
]
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
        <button class="btn theme-btn" type="button" @click="cycleTheme">
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

.theme-btn {
  flex: none;
}

main {
  padding-top: 24px;
}
</style>
