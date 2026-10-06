import { useState, type ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { describeError } from '@/lib/api'

/** "Are you sure?" box for actions that change or remove something. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive = false,
  busy = false,
  error,
  requireText,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  confirmLabel: string
  destructive?: boolean
  busy?: boolean
  error?: unknown
  /** For actions that cannot be undone: the user must type this text to enable the button. */
  requireText?: string
  onConfirm: () => void
}) {
  const [typed, setTyped] = useState('')
  // Start empty every time the dialog opens (React's "adjust state on prop change" pattern).
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setTyped('')
  }
  const blocked = requireText !== undefined && typed.trim() !== requireText

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!blocked) onConfirm()
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {error != null && (
            <Alert variant="destructive">
              <AlertDescription>{describeError(error)}</AlertDescription>
            </Alert>
          )}
          {requireText !== undefined && (
            <Field
              label={`Type ${requireText} to confirm`}
              autoComplete="off"
              spellCheck={false}
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant={destructive ? 'destructive' : 'default'} busy={busy} disabled={blocked}>
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}