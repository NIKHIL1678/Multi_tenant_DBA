import type { LucideIcon } from 'lucide-react'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'

/** Placeholder for sections whose screens are built in the next steps. */
export function ComingSoonPage({ title, description, icon }: { title: string; description: string; icon: LucideIcon }) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState icon={icon} title={`${title} is on its way`} description="This screen is being built next. The API behind it is already live." />
    </>
  )
}