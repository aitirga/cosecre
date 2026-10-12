<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { usePlatform } from '../../platform'
import type { BrowserCredentialsStatus } from '../../browser/contract'
const browser = usePlatform().browser
const form = reactive({ username: '', password: '', automatic: false })
const saved = ref<BrowserCredentialsStatus | null>(null)
const loading = ref(true)
const pending = ref(false)
const error = ref('')
const success = ref('')
const dirty = computed(() => saved.value && (form.username !== saved.value.username || form.automatic !== saved.value.automatic || Boolean(form.password)))
function apply(value: BrowserCredentialsStatus) {
  saved.value = value; form.username = value.username; form.password = ''; form.automatic = value.automatic
}
async function load() {
  loading.value = true; error.value = ''
  try { if (browser) apply(await browser.credentialsStatus('sfera')) }
  catch (e) { error.value = e instanceof Error ? e.message : 'No es pot llegir l’accés personal.' }
  finally { loading.value = false }
}
async function save() {
  if (!browser || pending.value) return
  pending.value = true; error.value = ''; success.value = ''
  try {
    apply(await browser.saveCredentials('sfera', { username: form.username, automatic: form.automatic, ...(form.password ? { password: form.password } : {}) }))
    success.value = 'Accés personal desat en aquest dispositiu.'
  } catch (e) { error.value = e instanceof Error ? e.message : 'No es pot desar l’accés personal.' }
  finally { pending.value = false }
}
async function remove() {
  if (!browser || pending.value) return
  pending.value = true; error.value = ''; success.value = ''
  try { apply(await browser.removeCredentials('sfera')); success.value = 'Credencials personals eliminades d’aquest dispositiu.' }
  catch (e) { error.value = e instanceof Error ? e.message : 'No es poden eliminar les credencials.' }
  finally { pending.value = false }
}
onMounted(load)
onBeforeUnmount(() => { form.password = '' })
</script>
<template>
  <section class="credentials">
    <h3>El meu accés a Esfer@</h3>
    <p class="text-muted">Cada secretari o secretària desa les seves pròpies credencials, separades per compte de Cosecre i Hub. Només s'utilitzen en aquest dispositiu.</p>
    <p v-if="loading" role="status">Carregant l’accés personal…</p>
    <form v-else-if="saved" autocomplete="off" @submit.prevent="save">
      <fieldset :disabled="pending || !saved.encryptionAvailable">
        <label class="field">Usuari de GICAR<input v-model="form.username" class="input" maxlength="200" autocomplete="username" @input="success = ''" /></label>
        <label class="field">Contrasenya<input v-model="form.password" class="input" type="password" maxlength="4096" autocomplete="new-password" :placeholder="saved.configured ? 'Desada · deixa en blanc per conservar-la' : 'Introdueix la contrasenya d’Esfer@'" @input="success = ''" /></label>
        <label class="toggle"><input v-model="form.automatic" type="checkbox" @change="success = ''" /><span>Iniciar sessió automàticament a GICAR</span></label>
        <p v-if="saved.configured" class="text-muted">Hi ha una contrasenya desada. Cosecre no la retorna ni la mostra en reobrir aquesta pantalla.</p>
        <div class="actions"><button class="btn btn-primary" :disabled="!dirty">{{ pending ? 'Desant…' : 'Desar el meu accés' }}</button><button class="btn btn-ghost" type="button" :disabled="!dirty" @click="apply(saved); success = ''">Descartar</button></div>
      </fieldset>
      <button class="btn btn-ghost" type="button" :disabled="pending || !saved.configured" @click="remove">Eliminar les meves credencials d’aquest dispositiu</button>
      <p v-if="!saved.encryptionAvailable" class="notice notice-gold" role="status">El sistema no disposa d’un magatzem segur. Pots iniciar sessió manualment al navegador.</p>
    </form>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    <button v-if="!loading && !saved" class="btn btn-secondary" @click="load">Tornar-ho a provar</button>
    <p v-if="success" role="status">{{ success }}</p>
    <p class="text-muted">La contrasenya es xifra amb el magatzem segur del sistema operatiu. No es desa al Hub ni es comparteix amb altres persones. L'accés automàtic reconeix només el formulari de GICAR; si demana un segon factor o canvia el formulari, completa l'accés manualment.</p>
  </section>
</template>
<style scoped>
.credentials { display: grid; gap: 12px; border-top: 1px solid var(--line); padding-top: 20px; }
form, fieldset { display: grid; gap: 12px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.field { display: grid; gap: 6px; }
.actions { display: flex; gap: 12px; flex-wrap: wrap; }
</style>
