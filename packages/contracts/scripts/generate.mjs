#!/usr/bin/env node
/**
 * Generate TypeScript types from Commerce API OpenAPI spec.
 * Run: pnpm --filter yasargold-contracts generate
 */
import { existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { execSync } from 'child_process'

const __dirname = dirname(fileURLToPath(import.meta.url))
const openapiPath = resolve(__dirname, '../../../apps/commerce-api/openapi.json')
const outPath = resolve(__dirname, '../src/api-types.ts')

if (!existsSync(openapiPath)) {
  console.error('┌─────────────────────────────────────────────────────────────────┐')
  console.error('│  openapi.json not found. To generate types:                     │')
  console.error('│                                                                   │')
  console.error('│  1. Run the Commerce API:                                        │')
  console.error('│     cd apps/commerce-api && uvicorn yasargold_commerce.main:app  │')
  console.error('│                                                                   │')
  console.error('│  2. Export the spec:                                             │')
  console.error('│     curl http://localhost:8000/openapi.json > \\                  │')
  console.error('│       apps/commerce-api/openapi.json                             │')
  console.error('│                                                                   │')
  console.error('│  3. Re-run: pnpm --filter yasargold-contracts generate            │')
  console.error('└─────────────────────────────────────────────────────────────────┘')
  process.exit(1)
}

console.log('Generating types from', openapiPath)
execSync(
  `npx openapi-typescript "${openapiPath}" --output "${outPath}"`,
  { stdio: 'inherit' }
)
console.log('Generated:', outPath)
