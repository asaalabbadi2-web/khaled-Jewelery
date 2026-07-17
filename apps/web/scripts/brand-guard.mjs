#!/usr/bin/env node
/**
 * Brand guard — CI gate (FC-5 / spec brand constraint).
 * Fails if the internal codename "yasargold" appears in any string
 * literal inside apps/web/src/. Customer-facing UI must never expose it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const SRC_DIR = join(__dirname, '../src')
const FORBIDDEN = 'yasargold'

function walk(dir) {
  const hits = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      hits.push(...walk(full))
    } else if (/\.(ts|tsx|js|jsx|json|css|html)$/.test(entry)) {
      hits.push(full)
    }
  }
  return hits
}

const violations = []

for (const file of walk(SRC_DIR)) {
  const content = readFileSync(file, 'utf8')
  const lines = content.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    // Only flag string literals — allow identifiers in import paths and comments
    // Pattern: FORBIDDEN inside quotes or template literals
    const inString = /['"`]([^'"`]*yasargold[^'"`]*)['"`]/.test(line)
    if (inString) {
      violations.push(`${relative(SRC_DIR, file)}:${i + 1}: ${line.trim()}`)
    }
  }
}

if (violations.length > 0) {
  console.error(
    `\n[brand-guard] FAIL — internal codename "${FORBIDDEN}" found in string literals:\n`,
  )
  for (const v of violations) {
    console.error(`  ${v}`)
  }
  console.error(
    '\nCustomer-facing strings must use BRAND_NAME from src/lib/brand.ts\n',
  )
  process.exit(1)
}

console.log(`[brand-guard] OK — no "${FORBIDDEN}" in string literals under src/`)
