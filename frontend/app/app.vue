<script setup lang="ts">
import { onMounted } from 'vue'

const { restorePlain } = useGlossary()
const { restoreTheme } = useTheme()

/** `SidebarProvider` decides its own initial state from `document.cookie`,
 *  which the server does not have - so it would always render expanded and
 *  then snap shut on hydration. Reading the cookie through Nuxt instead means
 *  the first server render already knows. */
const sidebarOpen = useCookie<boolean>('sidebar_state', { default: () => true })

onMounted(() => {
  restoreTheme()
  restorePlain()
})
</script>

<template>
  <SidebarProvider :default-open="sidebarOpen">
    <AppSidebar />
    <SidebarInset class="min-w-0">
      <header
        class="bg-card sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b px-4"
      >
        <SidebarTrigger class="-ml-1" />
        <NuxtLink to="/" class="font-semibold tracking-[-0.01em] no-underline md:hidden">
          Hevy&nbsp;Coach
        </NuxtLink>
      </header>

      <main class="mx-auto w-full max-w-[1180px] px-6 pt-6 pb-18">
        <NuxtPage />
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
