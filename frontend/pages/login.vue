<template>
  <div class="relative min-h-[100dvh] bg-void flex flex-col items-center justify-center px-6">
    <div class="login-enter w-full max-w-[360px]">
      <div class="flex flex-col items-center mb-10 text-center">
        <img src="/logo.png" alt="xstream" class="w-[88px] h-[88px] mb-6 rounded-[22px] shadow-card" />
        <h1 class="text-[34px] font-bold text-foreground leading-tight">xstream</h1>
        <p class="mt-1.5 text-[15px] text-foreground-muted">{{ randomGreeting }}</p>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <div class="relative" :class="shake ? 'animate-shake' : ''">
          <input
            ref="inputRef"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="Passcode"
            aria-label="Passcode"
            class="w-full h-[52px] px-12 rounded-2xl bg-white shadow-card border text-foreground text-[17px] text-center placeholder:text-foreground-muted/60 outline-none transition-[border-color,box-shadow] duration-200 focus:border-accent/40 focus:shadow-[0_0_0_4px_rgba(255,55,95,0.10)]"
            :class="error ? 'border-danger/40' : 'border-transparent'"
            @input="error = ''"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full flex items-center justify-center text-foreground-muted/60 hover:text-foreground-muted hover:bg-black/[0.04] transition"
            :aria-label="showPassword ? 'Hide passcode' : 'Show passcode'"
            @click="showPassword = !showPassword"
          >
            <svg v-if="!showPassword" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-6.5 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94" />
              <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19" />
              <line x1="2" y1="2" x2="22" y2="22" />
            </svg>
          </button>
        </div>

        <p class="min-h-[1.5em] text-[14px] text-danger text-center">{{ error }}</p>

        <button type="submit" class="btn btn-primary w-full h-[52px] text-[17px]" :disabled="!password.trim()">
          Enter
        </button>
      </form>
    </div>

    <p class="absolute bottom-[max(24px,env(safe-area-inset-bottom))] text-[12px] text-foreground-muted/60">{{ randomFooter }}</p>
  </div>
</template>

<script setup lang="ts">
/* Login page — daily rotating password validation */
definePageMeta({ layout: false })

const password = ref('')
const showPassword = ref(false)
const error = ref('')
const shake = ref(false)
const inputRef = ref<HTMLInputElement>()

// Whimsical greetings rotation
const greetings = [
  'Say the word and you\'re in',
  'Open sesame... no wait, this one',
  'Shhh, keep it down',
  'Welcome to the grown-up world',
  'Got your invitation?',
  'Wrong passcode summons ghosts',
  'Welcome back, old friend',
]
const randomGreeting = greetings[Math.floor(Math.random() * greetings.length)]

// Whimsical footer
const footers = [
  'Today\'s fortune: great for viewing',
  'Don\'t forget the popcorn',
  'Wrong passwords summon ghosts',
  'Please silence your devices',
  'It\'s late, keep it quiet',
]
const randomFooter = footers[Math.floor(Math.random() * footers.length)]

function todayPassword(): string {
  const d = new Date()
  const yy = (d.getFullYear() % 100).toString().padStart(2, '0')
  const mm = (d.getMonth() + 1).toString().padStart(2, '0')
  const dd = d.getDate().toString().padStart(2, '0')
  return `rn${yy}${mm}${dd}${d.getDate() % 2}`
}

function submit() {
  const input = password.value.trim()
  if (input === todayPassword()) {
    const auth = useCookie('xstream_auth', { maxAge: 86400, path: '/' })
    auth.value = 'ok'
    navigateTo('/')
  } else {
    error.value = 'Incorrect passcode'
    shake.value = true
    password.value = ''
    inputRef.value?.focus()
    setTimeout(() => { shake.value = false }, 500)
  }
}

onMounted(() => {
  inputRef.value?.focus()
})
</script>

<style scoped>
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-6px); }
  40% { transform: translateX(6px); }
  60% { transform: translateX(-4px); }
  80% { transform: translateX(4px); }
}
.animate-shake {
  animation: shake 0.4s ease-in-out;
}

@keyframes login-enter {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.login-enter {
  animation: login-enter 0.6s var(--ease-spring) both;
}
</style>
