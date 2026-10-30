<template>
  <Sheet v-model:open="open" :title="title" :subtitle="subtitle">
    <form class="space-y-4" @submit.prevent="submit">
      <div class="flex justify-center pt-1 pb-2">
        <div
          class="w-14 h-14 rounded-full flex items-center justify-center"
          :class="mode === 'unlock' ? 'bg-accent/10 text-accent' : 'bg-fill text-foreground-muted'"
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>
      </div>
      <p v-if="hint" class="text-[14px] text-foreground-muted text-center leading-relaxed px-1">{{ hint }}</p>
      <div>
        <label class="sr-only" for="vault-password">{{ passwordLabel }}</label>
        <input
          id="vault-password"
          ref="pwRef"
          v-model="password"
          type="password"
          autocomplete="off"
          class="field w-full"
          :placeholder="passwordLabel"
        />
      </div>
      <div v-if="needsConfirm">
        <label class="sr-only" for="vault-password-confirm">Confirm password</label>
        <input
          id="vault-password-confirm"
          v-model="confirm"
          type="password"
          autocomplete="off"
          class="field w-full"
          placeholder="Confirm password"
        />
      </div>
      <div v-if="mode === 'change'">
        <label class="sr-only" for="vault-password-new">New password</label>
        <input
          id="vault-password-new"
          v-model="newPassword"
          type="password"
          autocomplete="off"
          class="field w-full"
          placeholder="New password"
        />
      </div>
      <p v-if="error" class="text-[14px] text-danger">{{ error }}</p>
      <div class="flex justify-end gap-2 pt-1">
        <button type="button" class="btn btn-secondary" @click="open = false">Cancel</button>
        <button type="submit" class="btn btn-primary" :disabled="busy || !canSubmit">
          <span v-if="busy" class="spinner w-4 h-4" />
          <span v-else>{{ submitLabel }}</span>
        </button>
      </div>
    </form>
  </Sheet>
</template>

<script setup lang="ts">
export type VaultSheetMode = 'unlock' | 'encrypt' | 'decrypt' | 'change'

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{
  mode: VaultSheetMode
  targetName?: string
  targetKind?: 'file' | 'dir'
}>()
const emit = defineEmits<{
  submit: [payload: { password: string; newPassword?: string }]
}>()

const password = ref('')
const confirm = ref('')
const newPassword = ref('')
const error = ref('')
const busy = ref(false)
const pwRef = ref<HTMLInputElement>()

const needsConfirm = computed(() => props.mode === 'encrypt')
const title = computed(() => {
  if (props.mode === 'unlock') return 'Unlock'
  if (props.mode === 'encrypt') return 'Encrypt'
  if (props.mode === 'decrypt') return 'Remove encryption'
  return 'Change password'
})
const subtitle = computed(() => props.targetName)
const passwordLabel = computed(() => {
  if (props.mode === 'change') return 'Current password'
  if (props.mode === 'decrypt') return 'Password to decrypt'
  return 'Password'
})
const submitLabel = computed(() => {
  if (props.mode === 'unlock') return 'Unlock'
  if (props.mode === 'encrypt') return 'Encrypt'
  if (props.mode === 'decrypt') return 'Decrypt'
  return 'Update'
})
const hint = computed(() => {
  if (props.mode === 'encrypt' && props.targetKind === 'dir') {
    return 'This folder and new uploads inside it will be encrypted. Existing files are encrypted now.'
  }
  if (props.mode === 'encrypt') return 'The file is encrypted in your browser before upload. Only someone with the password can read it.'
  if (props.mode === 'unlock') return 'Enter the password you set when encrypting.'
  return undefined
})

const canSubmit = computed(() => {
  if (!password.value.trim()) return false
  if (needsConfirm.value && password.value !== confirm.value) return false
  if (props.mode === 'change' && !newPassword.value.trim()) return false
  return true
})

watch(open, (v) => {
  if (v) {
    password.value = ''
    confirm.value = ''
    newPassword.value = ''
    error.value = ''
    busy.value = false
    nextTick(() => pwRef.value?.focus())
  }
})

function setError(msg: string) {
  error.value = msg
  busy.value = false
}

function setBusy(v: boolean) {
  busy.value = v
}

function submit() {
  if (!canSubmit.value) return
  error.value = ''
  busy.value = true
  emit('submit', {
    password: password.value,
    newPassword: props.mode === 'change' ? newPassword.value : undefined,
  })
}

defineExpose({ setError, setBusy, close: () => { open.value = false; busy.value = false } })
</script>
