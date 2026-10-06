  import { History, Settings } from 'lucide-react'
import { createBrowserRouter } from 'react-router'

import { HomeLayout } from '@/app/layouts/home-layout'
import { TenantLayout } from '@/app/layouts/tenant-layout'
import { RequireAuth } from '@/app/require-auth'
import { LoginPage } from '@/features/auth/login-page'
import { ComingSoonPage } from '@/features/common/coming-soon-page'
import { NotFoundContent, NotFoundPage } from '@/features/common/not-found-page'
import { ConnectorsPage } from '@/features/connectors/connectors-page'
import { DatabasesPage } from '@/features/datasources/databases-page'
import { EnvironmentsPage } from '@/features/environments/environments-page'
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
          { path: 'databases', element: <DatabasesPage /> },
          { path: 'environments', element: <EnvironmentsPage /> },
          { path: 'connectors', element: <ConnectorsPage /> },
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