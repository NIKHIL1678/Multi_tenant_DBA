import { Toaster as Sonner, type ToasterProps } from 'sonner'

import { useTheme } from '@/lib/theme-context'

/** Pop-up notifications ("Member invited", errors with their ref id). Use toast() from 'sonner'. */
export function Toaster(props: ToasterProps) {
  const { resolved } = useTheme()
  return (
    <Sonner
      theme={resolved}
      position="bottom-right"
      richColors
      closeButton
      toastOptions={{ classNames: { toast: 'font-sans' } }}
      {...props}
    />
  )
}