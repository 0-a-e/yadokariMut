import { createFileRoute } from '@tanstack/react-router'
import { App } from '../App'
import { parseExplorerSearch, type ExplorerSearch } from '../lib/explorerSearch'

/**
 * Map explorer at `/` with typed search params (Phase R1).
 * validateSearch never throws — invalid values are stripped.
 */
export const Route = createFileRoute('/')({
  validateSearch: (raw: Record<string, unknown>): ExplorerSearch =>
    parseExplorerSearch(raw),
  component: App,
})
