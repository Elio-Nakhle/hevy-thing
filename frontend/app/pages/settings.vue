<script setup lang="ts">
/** Settings: the lifter profile, and what the rest of the app reads it for. */
import type { Health, Profile } from '~/types/api'
import { fullDate } from '~/utils/format'

const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const { data: health } = await useFetch<Health>('/api/health')
</script>

<template>
  <div>
    <div class="page-head">
      <h1>Settings</h1>
      <p v-if="profile?.needs_setup" class="warn">Incomplete - some numbers are stand-ins.</p>
    </div>

    <ProfileForm />

    <section class="card data-card">
      <div class="card-head"><h2 class="card-title">Training log</h2></div>
      <p class="card-sub">Import from the dashboard - drop a Hevy CSV export on it.</p>
      <table class="data-table">
        <tbody>
          <tr>
            <td>Workouts</td>
            <td>{{ health?.workouts ?? 0 }}</td>
          </tr>
          <tr>
            <td>Last workout</td>
            <td>{{ fullDate(health?.last_workout) }}</td>
          </tr>
          <tr>
            <td>Last import</td>
            <td>{{ fullDate(health?.last_import) }}</td>
          </tr>
          <tr>
            <td>Export read</td>
            <td>{{ health?.imported_file ?? '-' }}</td>
          </tr>
          <tr>
            <td>Coach model</td>
            <td>{{ profile?.coach_model ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.warn {
  margin: 0;
  font-size: 13px;
  color: var(--serious);
}

.data-card {
  margin-top: 16px;
  max-width: 520px;
}

.data-table td:last-child {
  color: var(--text-secondary);
}
</style>
