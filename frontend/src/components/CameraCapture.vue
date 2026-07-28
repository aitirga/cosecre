<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from './AppIcon.vue'

const props = withDefaults(defineProps<{ autoStart?: boolean }>(), { autoStart: false })
const emit = defineEmits<{ captured: [file: File] }>()

const video = ref<HTMLVideoElement | null>(null)
const stream = ref<MediaStream | null>(null)
const error = ref('')
const active = ref(false)

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
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
    })
    active.value = true
    // The <video> only exists once `active` has rendered.
    await nextTick()
    if (video.value) {
      video.value.srcObject = stream.value
      await video.value.play()
    }
  } catch {
    error.value = 'Camera access was blocked. Check the browser camera permission and try again.'
  }
}

function stopCamera() {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  active.value = false
}

async function captureFrame() {
  if (!video.value) return
  const canvas = document.createElement('canvas')
  canvas.width = video.value.videoWidth || video.value.clientWidth
  canvas.height = video.value.videoHeight || video.value.clientHeight
  canvas.getContext('2d')?.drawImage(video.value, 0, 0)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', 0.92),
  )
  if (!blob) return
  emit('captured', new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }))
  stopCamera()
}

function handleFallbackSelection(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) emit('captured', file)
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
      <video ref="video" autoplay playsinline muted />
      <div class="camera-actions">
        <button class="btn btn-primary btn-sm" type="button" @click="captureFrame">
          <AppIcon name="camera" />
          Capture
        </button>
        <button class="btn btn-outline btn-sm" type="button" @click="stopCamera">Cancel</button>
      </div>
    </template>

    <template v-else>
      <AppIcon name="camera" :size="22" />
      <span class="camera-title">Photograph a document</span>
      <button
        v-if="liveCameraSupported"
        class="btn btn-outline btn-sm"
        type="button"
        @click="startCamera"
      >
        Open camera
      </button>
      <label v-else class="btn btn-outline btn-sm file-button">
        <input type="file" accept="image/*" capture="environment" @change="handleFallbackSelection" />
        <span>Take photo</span>
      </label>
      <p v-if="!liveCameraSupported" class="hint">
        Live preview needs HTTPS or localhost. Here, the button opens the system camera instead.
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
  padding: 10px;
  gap: 10px;
}

.camera-title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-700);
}

video {
  width: 100%;
  flex: 1;
  min-height: 150px;
  object-fit: cover;
  border-radius: var(--r-sm);
  background: var(--ink-900);
}

.camera-actions {
  display: flex;
  gap: 8px;
  width: 100%;
}

.camera-actions .btn {
  flex: 1;
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
  max-width: 32ch;
}

.error {
  color: var(--danger-700);
}
</style>
