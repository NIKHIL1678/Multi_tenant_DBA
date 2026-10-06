import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * A multi-line command or snippet with a Copy button in its header bar.
 * Long lines scroll inside the box, never the page, and nothing covers the text.
 */
export function CodeBlock({ code, label, className }: { code: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      // Clipboard blocked (e.g. not https): the text is selectable, so Ctrl+C still works.
    }
  }

  return (
    <div className={cn('min-w-0 overflow-hidden rounded-lg border bg-muted', className)}>
      <div className="flex items-center justify-between gap-2 border-b bg-card/60 py-1 pr-1 pl-3">
        <span className="truncate text-xs font-medium text-muted-foreground">{label}</span>
        <Button type="button" variant="ghost" size="sm" onClick={copy} className="shrink-0">
          {copied ? <Check className="text-success" /> : <Copy />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre
        aria-label={label}
        tabIndex={0}
        className="max-h-64 overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset"
      >
        {code}
      </pre>
    </div>
  )
}