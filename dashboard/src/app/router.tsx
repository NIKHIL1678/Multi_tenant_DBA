import { Database, History, Layers, PlugZap, Settings } from 'lucide-react'
import { createBrowserRouter } from 'react-router'

import { HomeLayout } from '@/app/layouts/home-layout'
import { TenantLayout } from '@/app/layouts/tenant-layout'
import { RequireAuth } from '@/app/require-auth'
import { LoginPage } from '@/features/auth/login-page'
import { ComingSoonPage } from '@/features/common/coming-soon-page'
import { NotFoundContent, NotFoundPage } from '@/features/common/not-found-page'
import { MembersPage } from '@/features/members/members-page'
import { CompaniesPage } from '@/features/tenants/companies-page'
import { OverviewPage } from '@/features/tenants/overview-page'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <HomeLayout />,
        children: [{ path: '/', element: <CompaniesPage /> }],
      },
      {
        path: '/t/:tenantId',
        element: <TenantLayout />,
        children: [
          { index: true, element: <OverviewPage /> },
          {
            path: 'databases',
            element: <ComingSoonPage icon={Database} title="Databases" description="Every database your connectors can reach." />,
          },
          {
            path: 'environments',
            element: <ComingSoonPage icon={Layers} title="Environments" description="Production, staging and the rest." />,
          },
          {
            path: 'connectors',
            element: <ComingSoonPage icon={PlugZap} title="Connectors" description="Programs inside your network that reach your databases." />,
          },
          { path: 'members', element: <MembersPage /> },
          {
            path: 'audit',
            element: <ComingSoonPage icon={History} title="Audit log" description="Who did what, and when." />,
          },
          {
            path: 'settings',
            element: <ComingSoonPage icon={Settings} title="Settings" description="Company name and details." />,
          },
          { path: '*', element: <NotFoundContent /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
])