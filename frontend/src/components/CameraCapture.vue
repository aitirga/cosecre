<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from './AppIcon.vue'

const props = withDefaults(defineProps<{ autoStart?: boolean }>(), { autoStart: false })
const emit = defineEmits<{ captured: [file: File] }>()

const video = ref<HTMLVideoElement | null>(null)
const stream = ref<MediaStream | null>(null)
const error = ref('')
const active = ref(false)
const flash = ref(false)

/**
 * The last few shots of this session, newest first. The camera stays open
 * between them: each one is queued the moment it is taken, so photographing a
 * pile of receipts is a series of taps rather than tap, wait, reopen.
 */
const shots = ref<{ id: number; url: string }[]>([])
const sessionCount = ref(0)
const MAX_THUMBS = 5

/**
 * `getUserMedia` exists but throws outside a secure context, so both halves of
 * the check matter: over plain HTTP on a LAN address there is no live preview
 * and the `capture` file input is the only way to reach the camera.
 */
const liveCameraSupported = computed(() => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia)
})

async function startCamera() {
  error.value = ''
  sessionCount.value = 0
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        // Ask for document-reading resolution; phones default to far less.
        width: { ideal: 2560 },
        height: { ideal: 1920 },
      },
    })
    active.value = true
    // The <video> only exists once `active` has rendered.
    await nextTick()
    if (video.value) {
      video.value.srcObject = stream.value
      await video.value.play()
    }
  } catch {
    error.value =
      "No s'ha pogut obrir la càmera. Revisa el permís de càmera del navegador i torna-ho a provar."
  }
}

function stopCamera() {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  active.value = false
  clearShots()
}

function clearShots() {
  shots.value.forEach((shot) => URL.revokeObjectURL(shot.url))
  shots.value = []
}

async function captureFrame() {
  if (!video.value) return
  const canvas = document.createElement('canvas')
  canvas.width = video.value.videoWidth || video.value.clientWidth
  canvas.height = video.value.videoHeight || video.value.clientHeight
  canvas.getContext('2d')?.drawImage(video.value, 0, 0)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', 0.9),
  )
  if (!blob) return
  flash.value = true
  window.setTimeout(() => (flash.value = false), 140)
  navigator.vibrate?.(30)

  sessionCount.value += 1
  const file = new File([blob], `foto-${Date.now()}.jpg`, { type: 'image/jpeg' })
  shots.value = [{ id: Date.now(), url: URL.createObjectURL(blob) }, ...shots.value]
  shots.value.slice(MAX_THUMBS).forEach((shot) => URL.revokeObjectURL(shot.url))
  shots.value = shots.value.slice(0, MAX_THUMBS)
  emit('captured', file)
}

function handleFallbackSelection(event: Event) {
  const input = event.target as HTMLInputElement
  Array.from(input.files ?? []).forEach((file) => emit('captured', file))
  input.value = ''
}

onMounted(() => {
  if (props.autoStart && liveCameraSupported.value) void startCamera()
})

watch(
  () => props.autoStart,
  (autoStart, previous) => {
    if (autoStart && !previous && liveCameraSupported.value && !active.value) void startCamera()
  },
)

onBeforeUnmount(stopCamera)
</script>

<template>
  <div class="camera" :class="{ live: active }">
    <template v-if="active">
      <div class="viewport">
        <video ref="video" autoplay playsinline muted />
        <span class="flash" :class="{ on: flash }" aria-hidden="true" />
        <span v-if="sessionCount" class="counter" aria-live="polite">
          {{ sessionCount }} {{ sessionCount === 1 ? 'foto a la cua' : 'fotos a la cua' }}
        </span>
      </div>

      <div v-if="shots.length" class="strip" aria-label="Últimes fotos">
        <img v-for="shot in shots" :key="shot.id" :src="shot.url" alt="" />
      </div>

      <div class="camera-actions">
        <button class="btn btn-primary shutter" type="button" @click="captureFrame">
          <AppIcon name="camera" />
          Fes foto
        </button>
        <button class="btn btn-outline" type="button" @click="stopCamera">
          {{ sessionCount ? 'Fet' : 'Tanca' }}
        </button>
      </div>
      <p class="hint">Cada foto és un document. Pots continuar fent-ne mentre es llegeixen.</p>
    </template>

    <template v-else>
      <AppIcon name="camera" :size="22" />
      <span class="camera-title">Fotografia documents</span>
      <button
        v-if="liveCameraSupported"
        class="btn btn-outline btn-sm"
        type="button"
        @click="startCamera"
      >
        Obre la càmera
      </button>
      <label v-else class="btn btn-outline btn-sm file-button">
        <input type="file" accept="image/*" capture="environment" @change="handleFallbackSelection" />
        <span>Fes una foto</span>
      </label>
      <p v-if="!liveCameraSupported" class="hint">
        La vista prèvia en directe necessita HTTPS. Aquí el botó obre la càmera del sistema; pots
        repetir-ho tantes vegades com calgui.
      </p>
      <p v-if="error" class="hint error">{{ error }}</p>
    </template>
  </div>
</template>

<style scoped>
.camera {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 132px;
  padding: 18px;
  text-align: center;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  color: var(--ink-400);
}

.camera.live {
  align-items: stretch;
  padding: 10px;
  gap: 8px;
}

.camera-title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-700);
}

.viewport {
  position: relative;
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--ink-900);
}

video {
  display: block;
  width: 100%;
  min-height: 180px;
  max-height: 56vh;
  object-fit: cover;
}

.flash {
  position: absolute;
  inset: 0;
  background: #fff;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.14s ease-out;
}

.flash.on {
  opacity: 0.7;
  transition: none;
}

.counter {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 8px;
  border-radius: var(--r-full);
  background: rgba(28, 25, 23, 0.72);
  color: #fff;
  font-size: var(--text-sm);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.strip {
  display: flex;
  gap: 6px;
  overflow: hidden;
}

.strip img {
  width: 44px;
  height: 44px;
  object-fit: cover;
  border-radius: var(--r-xs);
  border: 1px solid var(--line-strong);
  animation: drop-in 0.18s ease-out;
}

@keyframes drop-in {
  from {
    transform: translateY(-6px);
    opacity: 0;
  }
}

.camera-actions {
  display: flex;
  gap: 8px;
}

.shutter {
  flex: 1;
}

.camera.live .hint {
  margin: 0;
  text-align: left;
}

/* The input covers the label so the whole button is the file picker. */
.file-button {
  position: relative;
  overflow: hidden;
}

.file-button input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.hint {
  max-width: 40ch;
}

.error {
  color: var(--danger-700);
}

@media (prefers-reduced-motion: reduce) {
  .strip img {
    animation: none;
  }
}
</style>
