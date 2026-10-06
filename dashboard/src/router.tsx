import { createBrowserRouter } from 'react-router'

import { AppLayout } from '@/components/app-layout'
import { RequireAuth } from '@/components/require-auth'
import { HomePage } from '@/pages/home-page'
import { LoginPage } from '@/pages/login-page'
import { NotFoundPage } from '@/pages/not-found-page'
import { TenantOverviewPage } from '@/pages/tenant-overview-page'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <HomePage /> },
          { path: '/t/:tenantId', element: <TenantOverviewPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
])