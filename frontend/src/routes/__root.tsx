import { createRootRoute, Outlet } from '@tanstack/react-router'

/**
 * App shell. Map-heavy UI stays under a single child route so the layout
 * remains mounted while search params drive panels (id / compare).
 */
export const Route = createRootRoute({
  component: RootLayout,
})

function RootLayout() {
  return <Outlet />
}
