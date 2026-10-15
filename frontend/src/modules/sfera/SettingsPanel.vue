<script setup lang="ts">
import CredentialsPanel from './CredentialsPanel.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useAuth } from '../../composables/useAuth'
import { portalUrl } from '../../browser/url'
import { getSettings, saveSettings, type SferaSettings } from './settings'
const auth = useAuth()
const form = reactive<SferaSettings>({ access_url: '', centre: '' })
const saved = ref<SferaSettings | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref(false)
const dirty = computed(() => saved.value && JSON.stringify(form) !== JSON.stringify(saved.value))
async function load() {
  loading.value = true; error.value = ''
  try { saved.value = await getSettings(); Object.assign(form, saved.value) }
  catch (e) { error.value = e instanceof Error ? e.message : 'No es pot llegir la configuració.' }
  finally { loading.value = false }
}
async function save() {
  if (!auth.isAdmin.value || saving.value) return
  saving.value = true; error.value = ''; success.value = false
  try {
    const settings = { access_url: form.access_url.trim() ? portalUrl(form.access_url) : '', centre: form.centre.trim() }
    await saveSettings(settings); Object.assign(form, settings); saved.value = { ...settings }; success.value = true
  } catch (e) { error.value = e instanceof Error ? e.message : 'No es pot desar la configuració.' }
  finally { saving.value = false }
}
onMounted(load)
</script>
<template>
  <section class="card sfera-settings">
    <h2>Esfer@</h2>
    <p class="text-muted">Accés manual a la gestió econòmica del centre.</p>
    <p v-if="loading" role="status">Carregant la configuració…</p>
    <form v-else-if="saved" @submit.prevent="save">
      <fieldset :disabled="saving || !auth.isAdmin.value">
        <label class="field">URL d'accés<input v-model="form.access_url" class="input" type="url" maxlength="2048" placeholder="https://…" @input="success = false" /></label>
        <button class="btn btn-secondary" type="button" @click="form.access_url = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat/bfgh/gestioeconomica/#/'; success = false">Utilitzar el portal de formació</button>
        <p class="text-muted">Adreça inicial del portal, sense contrasenyes ni tokens. Deixa-la buida per desactivar l'accés.</p>
        <label class="field">Centre (opcional)<input v-model="form.centre" class="input" maxlength="200" placeholder="08013305 o Escola Ramon Berenguer III" @input="success = false" /></label>
        <p class="text-muted">Codi o nom del centre. En entrar, Esfer@ el tria automàticament al diàleg «Escolliu el centre»; n'hi ha prou amb un nom aproximat («ramon berenguer», «Comas i Sola»). Si no hi ha cap coincidència clara, el tries tu.</p>
        <div class="actions action-bar"><button class="btn btn-primary" :disabled="!dirty">{{ saving ? 'Desant…' : 'Desar' }}</button><button class="btn btn-ghost" type="button" :disabled="!dirty" @click="Object.assign(form, saved); success = false">Descartar</button><span v-if="dirty" role="status">Canvis sense desar</span></div>
      </fieldset>
    </form>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    <button v-if="!loading && !saved" class="btn btn-secondary" @click="load">Tornar-ho a provar</button>
    <p v-if="success" role="status">Configuració desada.</p>
    <p class="text-muted">La URL i el centre es desen al Hub i es comparteixen amb les persones autoritzades. Només l'administrador les pot editar. Inicia sessió personalment al portal: Les credencials personals es configuren a continuació i es desen xifrades només al dispositiu. A l'escriptori, les cookies es conserven en aquest dispositiu, separades per compte i Hub. «Esborrar sessió» elimina les dades locals del portal.</p>
    <CredentialsPanel />
    <RouterLink class="btn btn-secondary" :to="{ name: 'sfera' }">Obrir Esfer@</RouterLink>
  </section>
</template>
<style scoped>
.sfera-settings { display: grid; gap: 16px; padding: 24px; }
fieldset { display: grid; gap: 12px; border: 0; padding: 0; margin: 0; min-width: 0; }
.field { display: grid; gap: 6px; }
/* Full-bleed across the card's 24px padding, closed above and below: it sits
   mid-card, with more notes after it. */
.actions { margin: 4px -24px; padding-inline: 24px; border-bottom: 1px solid var(--line-strong); }
</style>
