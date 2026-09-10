<script setup lang="ts">
/**
 * The app's navigation.
 *
 * Links are grouped by what you are doing rather than by which endpoint feeds
 * them: deciding today's session, looking back at what happened, or checking a
 * number against a goal. A flat list of eight was already hard to scan in the
 * header, and every horizon on the roadmap adds to it.
 */
import {
  ClipboardList,
  Dumbbell,
  Gauge,
  History,
  LayoutDashboard,
  MessageCircle,
  Monitor,
  Moon,
  Settings,
  Sun,
  Trophy,
  Type,
} from '@lucide/vue'
import { computed } from 'vue'
import type { Profile } from '~/types/api'

const { plain, togglePlain } = useGlossary()
const { theme, cycleTheme } = useTheme()
const route = useRoute()

// Same shared key as `useUnits`, so this costs no extra request.
const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })

/** The Total page is only meaningful for a goal judged on a total, so it is
 *  offered only then - a hypertrophy log has no main lifts to add up. */
const groups = computed(() => [
  {
    label: 'Plan',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/next', label: 'Next session', icon: ClipboardList },
    ],
  },
  {
    label: 'Review',
    items: [
      { to: '/workouts', label: 'Workouts', icon: History },
      { to: '/exercises', label: 'Exercises', icon: Dumbbell },
    ],
  },
  {
    label: 'Goals',
    items: [
      { to: '/strength', label: 'Strength standards', icon: Gauge },
      ...(profile.value?.tracks_total
        ? [{ to: '/total', label: 'Your total', icon: Trophy }]
        : []),
    ],
  },
  {
    label: 'Coach',
    items: [{ to: '/coach', label: 'Ask the coach', icon: MessageCircle }],
  },
])

/** A section stays lit while you are inside it, so `/workouts/1234` keeps
 *  Workouts marked - but `/` would otherwise match everything. */
function isActive(to: string): boolean {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}

const themeIcon = computed(() =>
  theme.value === 'light' ? Sun : theme.value === 'dark' ? Moon : Monitor,
)
const themeLabel = computed(() =>
  theme.value === 'light' ? 'Light' : theme.value === 'dark' ? 'Dark' : 'Auto',
)
</script>

<template>
  <Sidebar collapsible="icon">
    <SidebarHeader>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" as-child>
            <NuxtLink to="/">
              <span
                class="bg-primary text-primary-foreground flex aspect-square size-8 items-center
                       justify-center rounded-lg"
              >
                <Dumbbell class="size-4" />
              </span>
              <span class="grid flex-1 text-left leading-tight">
                <span class="text-foreground truncate font-semibold">Hevy Coach</span>
                <span class="truncate text-xs">Training analytics</span>
              </span>
            </NuxtLink>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup v-for="group in groups" :key="group.label">
        <SidebarGroupLabel>{{ group.label }}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="item in group.items" :key="item.to">
              <SidebarMenuButton as-child :is-active="isActive(item.to)" :tooltip="item.label">
                <NuxtLink :to="item.to">
                  <component :is="item.icon" />
                  <span>{{ item.label }}</span>
                </NuxtLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            :tooltip="plain
              ? 'Switch to the technical names for each number'
              : 'Rename every number in plain English'"
            :aria-pressed="plain"
            @click="togglePlain"
          >
            <Type />
            <span>{{ plain ? 'Plain English' : 'Technical names' }}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton :tooltip="`Theme: ${themeLabel}`" @click="cycleTheme">
            <component :is="themeIcon" />
            <span>{{ themeLabel }} theme</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton as-child :is-active="isActive('/settings')" tooltip="Settings">
            <NuxtLink to="/settings">
              <Settings />
              <span>Settings</span>
            </NuxtLink>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>

    <SidebarRail />
  </Sidebar>
</template>
