import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** A read-only value (link, command, key) with a Copy button. */
export function CopyField({ value, label, className }: { value: string; label: string; className?: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      // Clipboard blocked (e.g. not https): select the text so the user can press Ctrl+C.
      inputRef.current?.select()
    }
  }

  return (
    <div className={cn('flex gap-2', className)}>
      <input
        ref={inputRef}
        readOnly
        value={value}
        aria-label={label}
        onFocus={(e) => e.currentTarget.select()}
        className="h-9 min-w-0 flex-1 rounded-md border border-input bg-muted px-3 font-mono text-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
      <Button type="button" variant="outline" onClick={copy} className="shrink-0">
        {copied ? <Check className="text-success" /> : <Copy />}
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}