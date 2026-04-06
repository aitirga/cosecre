<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ autoStart?: boolean }>(), { autoStart: false })

const emit = defineEmits<{
  captured: [file: File]
}>()

const video = ref<HTMLVideoElement | null>(null)
const stream = ref<MediaStream | null>(null)
const error = ref('')
const active = ref(false)
const liveCameraSupported = computed(() => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false
  }

  return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia)
})

const actionLabel = computed(() => (liveCameraSupported.value ? 'Open Camera' : 'Take Photo'))

async function startCamera() {
  error.value = ''
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
    })
    active.value = true
    await nextTick() // wait for <video> to be rendered before assigning srcObject
    if (video.value) {
      video.value.srcObject = stream.value
      await video.value.play()
    }
  } catch {
    error.value = 'Camera access was blocked. Check your browser camera permissions and try again.'
  }
}

function openCamera() {
  error.value = ''

  if (!liveCameraSupported.value) {
    return
  }

  void startCamera()
}

function stopCamera() {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  active.value = false
}

async function captureFrame() {
  if (!video.value) {
    return
  }
  const canvas = document.createElement('canvas')
  canvas.width = video.value.videoWidth || video.value.clientWidth
  canvas.height = video.value.videoHeight || video.value.clientHeight
  const context = canvas.getContext('2d')
  context?.drawImage(video.value, 0, 0)
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92))
  if (!blob) {
    return
  }
  emit('captured', new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }))
  stopCamera()
}

function handleFallbackSelection(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('captured', file)
  }
  input.value = ''
}

onMounted(() => {
  if (props.autoStart && liveCameraSupported.value) {
    void startCamera()
  }
})

watch(
  () => props.autoStart,
  (autoStart, previous) => {
    if (autoStart && !previous && liveCameraSupported.value && !active.value) {
      void startCamera()
    }
  },
)

onBeforeUnmount(stopCamera)
</script>

<template>
  <div class="camera-card" :class="{ 'camera-card--active': active }">
    <div v-if="active" class="preview">
      <video ref="video" autoplay playsinline muted />
      <div class="actions">
        <button type="button" class="btn-primary" @click="captureFrame">Capture</button>
        <button type="button" class="btn-ghost" @click="stopCamera">Cancel</button>
      </div>
    </div>
    <div v-else class="idle">
      <svg
        class="camera-icon"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path
          d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"
        />
        <circle cx="12" cy="13" r="4" />
      </svg>
      <p class="camera-label">Use the camera for quick invoice capture.</p>
      <button v-if="liveCameraSupported" type="button" class="btn-camera" @click="openCamera">
        {{ actionLabel }}
      </button>
      <label v-else class="btn-camera btn-camera--fallback">
        <input
          class="camera-input"
          type="file"
          accept="image/*"
          capture="environment"
          @change="handleFallbackSelection"
        />
        <span>{{ actionLabel }}</span>
      </label>
      <p v-if="!liveCameraSupported" class="hint">
        Live preview needs HTTPS or localhost. On this device, the button will open the camera and
        upload the photo directly.
      </p>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.camera-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.camera-card {
  display: flex;
  flex-direction: column;
  border-radius: 20px;
  border: 2px solid rgba(49, 36, 29, 0.1);
  background: rgba(31, 55, 39, 0.03);
  overflow: hidden;
  min-height: 180px;
}

.idle {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 28px 20px;
  text-align: center;
}

.camera-icon {
  width: 36px;
  height: 36px;
  color: var(--muted);
}

.camera-label {
  font-size: 0.95rem;
  color: var(--muted);
}

.hint {
  max-width: 28ch;
  color: var(--muted);
  font-size: 0.8rem;
}

.btn-camera {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  background: rgba(31, 55, 39, 0.1);
  padding: 0.65rem 1.3rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-camera--fallback {
  overflow: hidden;
}

.btn-camera:hover {
  background: rgba(31, 55, 39, 0.16);
}

.preview {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 12px;
  padding: 12px;
}

video {
  flex: 1;
  width: 100%;
  min-height: 180px;
  object-fit: cover;
  border-radius: 14px;
  background: #000;
}

.actions {
  display: flex;
  gap: 10px;
}

.btn-primary,
.btn-ghost {
  border: 0;
  border-radius: 999px;
  padding: 0.75rem 1.2rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  flex: 1;
  background: var(--accent);
  color: white;
}

.btn-ghost {
  background: rgba(31, 55, 39, 0.08);
}

.error {
  color: var(--danger);
  font-size: 0.85rem;
}
</style>
