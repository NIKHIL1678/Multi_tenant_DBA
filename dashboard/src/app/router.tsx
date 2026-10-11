import { createBrowserRouter } from 'react-router'

import { HomeLayout } from '@/app/layouts/home-layout'
import { TenantLayout } from '@/app/layouts/tenant-layout'
import { RequireAuth } from '@/app/require-auth'
import { AuditPage } from '@/features/audit/audit-page'
import { LoginPage } from '@/features/auth/login-page'
import { SignupPage } from '@/features/auth/signup-page'
import { NotFoundContent, NotFoundPage } from '@/features/common/not-found-page'
import { ConnectorsPage } from '@/features/connectors/connectors-page'
import { DatabasesPage } from '@/features/datasources/databases-page'
import { EnvironmentsPage } from '@/features/environments/environments-page'
import { InvitePage } from '@/features/invitations/invite-page'
import { MembersPage } from '@/features/members/members-page'
import { CompaniesPage } from '@/features/tenants/companies-page'
import { OverviewPage } from '@/features/tenants/overview-page'
import { SettingsPage } from '@/features/tenants/settings-page'

export const router = createBrowserRouter([
  // Public: no sign-in needed.
  { path: '/login', element: <LoginPage /> },
  { path: '/signup', element: <SignupPage /> },
  { path: '/invite', element: <InvitePage /> },

  // Everything else needs a signed-in user.
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
          { path: 'audit', element: <AuditPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: '*', element: <NotFoundContent /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
])