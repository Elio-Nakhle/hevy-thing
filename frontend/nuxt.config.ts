export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  css: ['~/assets/css/main.css'],

  runtimeConfig: {
    public: {
      // Only used for display; requests go through the proxy below.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000',
    },
  },

  // Proxy /api to the FastAPI backend so the browser makes same-origin
  // requests - no CORS preflight, and no API base URL baked into the bundle.
  routeRules: {
    '/api/**': {
      proxy: `${process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000'}/api/**`,
    },
  },

  app: {
    head: {
      title: 'Hevy Coach',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'Training analytics, strength standards, and an AI coach.' },
      ],
    },
  },
})
