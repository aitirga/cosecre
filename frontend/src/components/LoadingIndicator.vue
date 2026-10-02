<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import BrandMark from './BrandMark.vue'
import { networkLoading } from '../api/loading'

const route = useRoute()
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { timer = setInterval(() => { now.value = Date.now() }, 250) })
onUnmounted(() => { clearInterval(timer) })
const booting = computed(() => route.matched.length === 0)
const elapsed = computed(() => now.value - networkLoading.startedAt.value)
const waiting = computed(() => networkLoading.pending.value > 0 && elapsed.value > 300)
const slow = computed(() => networkLoading.pending.value > 0 && elapsed.value > 3000)
</script>

<template>
  <section v-if="booting" class="startup-loading" aria-label="Carregant Cosecre" aria-busy="true">
    <div class="startup-card">
      <BrandMark :size="48" />
      <h1>Cosecre</h1>
      <p role="status">{{ slow ? 'Connectant amb Cosecre…' : 'Carregant…' }}</p>
      <div class="loading-track" role="progressbar" aria-label="Carregant"><span /></div>
      <p class="loading-hint">{{ slow ? 'Potser el servidor s\'està despertant. Pot trigar uns segons.' : 'Preparant-ho tot.' }}</p>
    </div>
  </section>
  <div v-else-if="waiting" class="request-loading">
    <div class="loading-track" role="progressbar" aria-label="Esperant el servidor"><span /></div>
    <p v-if="slow" role="status">Esperant el servidor…</p>
  </div>
</template>

<style scoped>
.startup-loading { min-height: 100dvh; display: grid; place-items: center; padding: 24px; background: #fbf5ea; }
.startup-card { width: min(100%, 340px); text-align: center; color: #36342e; }
.startup-card svg { margin: 0 auto 12px; }
.startup-card h1 { margin: 0 0 20px; font-size: 28px; }
.startup-card p { margin: 12px 0; }
.startup-card .loading-hint { min-height: 44px; font-size: 14px; color: #726d61; }
.loading-track { height: 4px; overflow: hidden; border-radius: 4px; background: #e8decb; }
.loading-track span { display: block; width: 35%; height: 100%; background: #b83c14; border-radius: inherit; animation: loading-slide 1.4s ease-in-out infinite; }
.request-loading { position: fixed; inset: 0 0 auto; z-index: 2000; pointer-events: none; }
.request-loading p { width: fit-content; margin: 8px auto; padding: 8px 14px; border: 1px solid #e8decb; border-radius: 8px; background: #fbf5ea; color: #36342e; font-size: 14px; box-shadow: 0 2px 8px #0001; }
@keyframes loading-slide { from { transform: translateX(-100%); } to { transform: translateX(386%); } }
@media (prefers-reduced-motion: reduce) { .loading-track span { animation: none; width: 100%; opacity: .65; } }
</style>
