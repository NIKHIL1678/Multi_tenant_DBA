// Everything the dashboard asks the backend about members, roles and invitations.
// After a change we update the cached list directly with what the server returned,
// so the screen changes at once without reloading the whole list.

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { tenantKeys } from '@/features/tenants/api'
import { api } from '@/lib/api'
import type { Invitation, InvitationCreated, Member, Role } from '@/lib/types'

export const memberKeys = {
  list: (tenantId: string) => ['tenants', tenantId, 'members'] as const,
  roles: (tenantId: string) => ['tenants', tenantId, 'roles'] as const,
  invitations: (tenantId: string) => ['tenants', tenantId, 'invitations'] as const,
}

// ---- reads -----------------------------------------------------------------------------------

export function useRoles(tenantId: string) {
  return useQuery({
    queryKey: memberKeys.roles(tenantId),
    queryFn: () => api<Role[]>(`/v1/tenants/${tenantId}/roles`),
    staleTime: 5 * 60_000, // roles almost never change
  })
}

export function useMembers(tenantId: string) {
  return useQuery({
    queryKey: memberKeys.list(tenantId),
    queryFn: () => api<Member[]>(`/v1/tenants/${tenantId}/members`),
  })
}

/** Pending invitations. Only people who can manage members may see them. */
export function useInvitations(tenantId: string, { enabled }: { enabled: boolean }) {
  return useQuery({
    queryKey: memberKeys.invitations(tenantId),
    queryFn: () => api<Invitation[]>(`/v1/tenants/${tenantId}/invitations`),
    enabled,
  })
}

// ---- member changes --------------------------------------------------------------------------

function replaceMember(queryClient: QueryClient, tenantId: string, updated: Member) {
  queryClient.setQueryData<Member[]>(memberKeys.list(tenantId), (list) =>
    list?.map((m) => (m.id === updated.id ? updated : m)),
  )
  // Your own role may have changed: refresh what the menus think you can do.
  void queryClient.invalidateQueries({ queryKey: tenantKeys.detail(tenantId), exact: true })
  void queryClient.invalidateQueries({ queryKey: tenantKeys.overview(tenantId) })
}

export function useUpdateMember(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memberId, ...body }: { memberId: string; role_id?: string; status?: 'active' | 'suspended' }) =>
      api<Member>(`/v1/tenants/${tenantId}/members/${memberId}`, { method: 'PATCH', body }),
    onSuccess: (member) => replaceMember(queryClient, tenantId, member),
  })
}

export function useSetEnvironmentRole(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memberId, environmentId, roleId }: { memberId: string; environmentId: string; roleId: string }) =>
      api<Member>(`/v1/tenants/${tenantId}/members/${memberId}/environments/${environmentId}`, {
        method: 'PUT',
        body: { role_id: roleId },
      }),
    onSuccess: (member) => replaceMember(queryClient, tenantId, member),
  })
}

export function useRemoveEnvironmentRole(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memberId, environmentId }: { memberId: string; environmentId: string }) =>
      api<void>(`/v1/tenants/${tenantId}/members/${memberId}/environments/${environmentId}`, { method: 'DELETE' }),
    onSuccess: (_, { memberId, environmentId }) => {
      queryClient.setQueryData<Member[]>(memberKeys.list(tenantId), (list) =>
        list?.map((m) =>
          m.id === memberId
            ? { ...m, environment_roles: m.environment_roles.filter((er) => er.environment_id !== environmentId) }
            : m,
        ),
      )
      void queryClient.invalidateQueries({ queryKey: tenantKeys.detail(tenantId), exact: true })
    },
  })
}

// ---- invitations -----------------------------------------------------------------------------

export function useCreateInvitation(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; role_id: string }) =>
      api<InvitationCreated>(`/v1/tenants/${tenantId}/invitations`, { method: 'POST', body }),
    // Re-inviting the same email replaces the old invitation, so reload rather than append.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memberKeys.invitations(tenantId) }),
  })
}

export function useRevokeInvitation(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (invitationId: string) =>
      api<void>(`/v1/tenants/${tenantId}/invitations/${invitationId}`, { method: 'DELETE' }),
    onSuccess: (_, invitationId) =>
      queryClient.setQueryData<Invitation[]>(memberKeys.invitations(tenantId), (list) =>
        list?.filter((i) => i.id !== invitationId),
      ),
  })
}