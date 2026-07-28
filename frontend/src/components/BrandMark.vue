<script setup lang="ts">
/**
 * The Cosecre mark: a bold C whose opening is a document slot, with a sheet
 * coming through it.
 *
 * Deliberately the same silhouette as cosecre-print's icon — they are sibling
 * apps and should look it — but in Cosecre's own palette: terracotta arc,
 * white sheet outlined in olive, gold accent.
 *
 * Rules that keep it legible at 16px:
 *   • no stroke thinner than 13 units on the 512 grid
 *   • the sheet is outlined, not plain white, or it dissolves into the tile
 *   • butt caps on the arc, so the gap reads as a slot and not a broken circle
 *
 * Keep this in sync with public/favicon.svg and build/icon.svg.
 */
withDefaults(defineProps<{ size?: number; tile?: boolean }>(), { size: 24, tile: true })
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
      <linearGradient :id="`cosecre-tile-${size}`" x1="0" y1="0" x2="0.3" y2="1">
        <stop offset="0" stop-color="#ffffff" />
        <stop offset="1" stop-color="#f7e9d4" />
      </linearGradient>
      <linearGradient :id="`cosecre-arc-${size}`" x1="0" y1="0" x2="0.4" y2="1">
        <stop offset="0" stop-color="#f68d68" />
        <stop offset="1" stop-color="#b83c14" />
      </linearGradient>
    </defs>

    <template v-if="tile">
      <rect x="16" y="16" width="480" height="480" rx="112" :fill="`url(#cosecre-tile-${size})`" />
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

    <!-- The C: a 260° arc opening to the right. -->
    <path
      d="M 329.7 350.9 A 132 132 0 1 1 329.7 161.1"
      transform="translate(-8 0)"
      fill="none"
      :stroke="`url(#cosecre-arc-${size})`"
      stroke-width="58"
    />

    <!-- The sheet passes through the gap without ever crossing the arc, which
         is what lets it carry an outline for free. -->
    <rect
      x="210"
      y="214"
      width="232"
      height="84"
      rx="19"
      fill="#ffffff"
      stroke="#3a5a3c"
      stroke-width="13"
    />
    <g fill="#3a5a3c" opacity="0.55">
      <rect x="248" y="238" width="152" height="13" rx="6.5" />
      <rect x="248" y="262" width="100" height="13" rx="6.5" />
    </g>
  </svg>
</template>
