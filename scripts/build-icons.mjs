/**
 * Rasterise the icon master for electron-builder.
 *
 *   brand/icon.svg  ->  desktop/build/icon.png  (1024x1024)
 *
 * Run with `npm run icons`. Needs librsvg:
 *
 *   brew install librsvg
 *
 * The output is committed on purpose. Packaging happens in CI on runners that
 * have no librsvg, so the build must never depend on this script having run —
 * it is a local authoring convenience only.
 *
 * ImageMagick is not an acceptable fallback here: its built-in SVG reader
 * renders the two gradients wrong.
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function which(binary) {
  try {
    return execFileSync('which', [binary], { encoding: 'utf8' }).trim() || null
  } catch {
    return null
  }
}

const rsvg = which('rsvg-convert')
if (!rsvg) {
  console.error('✗ rsvg-convert not found. Install it with: brew install librsvg')
  process.exit(1)
}

const output = join(repoRoot, 'desktop', 'build', 'icon.png')
mkdirSync(dirname(output), { recursive: true })

execFileSync(
  rsvg,
  [
    '--width=1024',
    '--height=1024',
    '--format=png',
    `--output=${output}`,
    join(repoRoot, 'brand', 'icon.svg'),
  ],
  { stdio: ['ignore', 'ignore', 'inherit'] },
)

console.log('✓ desktop/build/icon.png (1024x1024)')
