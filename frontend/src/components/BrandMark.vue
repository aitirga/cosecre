<script setup lang="ts">
/**
 * The Cosecre mark, "Aperture": a bold C whose opening is a paper slot, with a
 * sheet coming through it. It came from Cosecre-print and is now the whole
 * app's mark.
 *
 * Rules that keep it legible at 16px:
 *   • nothing thinner than 13 units on the 512 grid
 *   • the sheet is outlined, not plain white — on a pale tile an unoutlined
 *     sheet dissolves into the background
 *   • the sheet clears both ends of the arc, so the C never looks broken
 *   • butt caps on the arc, so the gap reads as a slot, not an unfinished ring
 *   • text lines left-aligned and unequal; centred equal ones read as "="
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
    :viewBox="tile ? '0 0 512 512' : '76 64 384 384'"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient :id="`${uid}-tile`" x1="0" y1="0" x2="0.3" y2="1">
        <stop offset="0" stop-color="#ffffff" />
        <stop offset="1" stop-color="#d7e7fa" />
      </linearGradient>
      <linearGradient :id="`${uid}-paper`" x1="0" y1="0" x2="0.35" y2="1">
        <stop offset="0" stop-color="#ffffff" />
        <stop offset="1" stop-color="#f2f7fe" />
      </linearGradient>
      <linearGradient :id="`${uid}-blue`" x1="0" y1="0" x2="0.4" y2="1">
        <stop offset="0" stop-color="#7ea8ee" />
        <stop offset="1" stop-color="#2f5aa8" />
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
        stroke="rgba(47,90,168,0.13)"
        stroke-width="2"
      />
    </template>

    <!-- The C: a 260-degree arc opening to the right. -->
    <path
      d="M 329.7 350.9 A 132 132 0 1 1 329.7 161.1"
      transform="translate(-8 0)"
      fill="none"
      :stroke="`url(#${uid}-blue)`"
      stroke-width="58"
    />

    <!-- The sheet passing through the slot, with two lines of text. -->
    <rect
      x="210"
      y="214"
      width="232"
      height="84"
      rx="19"
      :fill="`url(#${uid}-paper)`"
      stroke="#2f5aa8"
      stroke-width="13"
    />
    <g fill="#2f5aa8" opacity="0.5">
      <rect x="248" y="238" width="152" height="13" rx="6.5" />
      <rect x="248" y="262" width="100" height="13" rx="6.5" />
    </g>
  </svg>
</template>
