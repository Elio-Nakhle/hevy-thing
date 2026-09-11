<script setup lang="ts">
/** Settings: the lifter profile, and what the rest of the app reads it for. */
import { computed } from 'vue'
import type { CoachStatus, Health, Profile } from '~/types/api'
import { fullDate } from '~/utils/format'

const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const { data: health } = await useFetch<Health>('/api/health')
const { data: coach } = await useFetch<CoachStatus>('/api/coach')

/** Where the coach's model runs, which is the one thing here that can be
 *  missing outright rather than merely unset. */
const coachRuns = computed(() => {
  if (coach.value?.backend === 'cli') return 'Claude Code CLI on this machine'
  if (coach.value?.backend === 'api') return 'Anthropic API'
  return 'nothing yet - no API key and no Claude Code'
})
</script>

<template>
  <div>
    <div class="mb-[18px] flex flex-wrap items-baseline justify-between gap-4">
      <h1>Settings</h1>
      <p v-if="profile?.needs_setup" class="text-serious m-0 text-[13px]">
        Incomplete - some numbers are stand-ins.
      </p>
    </div>

    <ProfileForm />

    <Card class="mt-4 max-w-[520px]">
      <CardHeader>
        <CardTitle>Training log</CardTitle>
        <CardDescription>Import from the dashboard - drop a Hevy CSV export on it.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table class="numeric-table [&_td:last-child]:text-muted-foreground">
          <TableBody>
            <TableRow>
              <TableCell>Workouts</TableCell>
              <TableCell>{{ health?.workouts ?? 0 }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Last workout</TableCell>
              <TableCell>{{ fullDate(health?.last_workout) }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Last import</TableCell>
              <TableCell>{{ fullDate(health?.last_import) }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Export read</TableCell>
              <TableCell>{{ health?.imported_file ?? '-' }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Coach model</TableCell>
              <TableCell>{{ profile?.coach_model ?? '-' }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Coach runs on</TableCell>
              <TableCell :class="coach && !coach.ready && 'text-serious'">{{ coachRuns }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
