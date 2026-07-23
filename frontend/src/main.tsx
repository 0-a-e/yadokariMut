import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { CopilotKitProvider } from "@copilotkit/react-core/v2"
import { HttpAgent } from "@ag-ui/client"
import { router } from './router'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'
import './index.css'

const yadokariAgent = new HttpAgent({
  url: "/api/copilotkit",
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <CopilotKitProvider agents__unsafe_dev_only={{ "yadokari_agent": yadokariAgent }}>
      <RouterProvider router={router} />
    </CopilotKitProvider>
  </React.StrictMode>,
)
