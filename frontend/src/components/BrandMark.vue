<script setup lang="ts">
/**
 * The Cosecre mark: the C standing on a data table.
 *
 * Rules that keep it legible at 16px:
 *   • nothing thinner than 24 units on the 512 grid
 *   • the rows step down in weight, not size — at icon scale that is the only
 *     thing that still reads as "header, then data"
 *   • butt caps on the arc, so the gap in the C reads as deliberate
 *   • unequal columns; two equal ones read as a split rectangle
 *
 * Keep in sync with public/favicon.svg and brand/icon.svg, which carries the
 * full rationale.
 */
import { useId } from 'vue'

withDefaults(defineProps<{ size?: number; tile?: boolean }>(), { size: 24, tile: true })

// Gradient ids are document-global, so two marks on one page would otherwise
// fight over them — the header and the mobile bar render at the same time.
const uid = useId()
</script>

<template>
  <svg
    :width="size"
    :height="size"
    :viewBox="tile ? '0 0 512 512' : '84 82 344 344'"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient :id="`${uid}-tile`" x1="0" y1="0" x2="0.3" y2="1">
        <stop offset="0" stop-color="#ffffff" />
        <stop offset="1" stop-color="#f7e9d4" />
      </linearGradient>
      <linearGradient :id="`${uid}-arc`" x1="0" y1="0" x2="0.4" y2="1">
        <stop offset="0" stop-color="#f68d68" />
        <stop offset="1" stop-color="#b83c14" />
      </linearGradient>
    </defs>

    <template v-if="tile">
      <rect x="16" y="16" width="480" height="480" rx="112" :fill="`url(#${uid}-tile)`" />
      <rect
        x="16"
        y="16"
        width="480"
        height="480"
        rx="112"
        fill="none"
        stroke="rgba(28,25,23,0.10)"
        stroke-width="2"
      />
    </template>

    <!-- The C: a 260-degree arc opening to the right. -->
    <path
      d="M 311.3 263.9 A 86 86 0 1 1 311.3 132.1"
      fill="none"
      :stroke="`url(#${uid}-arc)`"
      stroke-width="54"
    />

    <!-- The table it stands on. -->
    <g fill="#3a5a3c">
      <rect x="96" y="326" width="182" height="30" rx="8" />
      <rect x="302" y="326" width="114" height="30" rx="8" />
    </g>
    <g fill="#3a5a3c" opacity="0.42">
      <rect x="96" y="364" width="182" height="26" rx="7" />
      <rect x="302" y="364" width="114" height="26" rx="7" />
    </g>
    <g fill="#3a5a3c" opacity="0.24">
      <rect x="96" y="398" width="182" height="26" rx="7" />
      <rect x="302" y="398" width="114" height="26" rx="7" />
    </g>
  </svg>
</template>
