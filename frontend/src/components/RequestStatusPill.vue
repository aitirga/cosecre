<script setup lang="ts">
import { computed } from 'vue'

import type { RequestStatus } from '../api/types'
import { STATUS_META } from '../requests'

const props = defineProps<{ status: RequestStatus }>()
const meta = computed(() => STATUS_META[props.status])
</script>

<template>
  <span class="badge" :class="meta.tone">{{ meta.label }}</span>
</template>
