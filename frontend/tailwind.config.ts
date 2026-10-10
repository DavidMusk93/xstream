import type { Config } from 'tailwindcss'

export default {
  content: [
    './components/**/*.{vue,js,ts}',
    './pages/**/*.{vue,js,ts}',
    './layouts/**/*.{vue,js,ts}',
    './composables/**/*.{js,ts}',
    './app.vue',
  ],
  theme: {
    extend: {
      colors: {
        void: '#F5F5F7',
        fill: '#F2F2F7',
        foreground: '#1D1D1F',
        'foreground-muted': '#86868B',
        accent: {
          DEFAULT: '#FF375F',
          hover: '#FF4D70',
        },
        success: '#30D158',
        warning: '#FF9F0A',
        danger: '#FF453A',
        info: '#0A84FF',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"SF Pro Display"', '"Helvetica Neue"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.04), 0 6px 24px rgba(0,0,0,0.04)',
        float: '0 2px 8px rgba(0,0,0,0.04), 0 16px 48px rgba(0,0,0,0.14)',
      },
      transitionTimingFunction: {
        spring: 'cubic-bezier(0.16, 1, 0.3, 1)',
        press: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      },
    },
  },
  plugins: [],
} as Config
