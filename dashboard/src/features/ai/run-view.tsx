import { AlertTriangle, Check, CircleDashed, Info, RotateCcw, Table2 } from 'lucide-react'
import { Fragment, type ReactNode } from 'react'

import { CodeBlock } from '@/components/code-block'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { isActive } from '@/features/ai/api'
import type { AgentFinding, AgentRun } from '@/lib/types'

const SEVERITY = {
  high: { label: 'High', variant: 'destructive' },
  medium: { label: 'Medium', variant: 'warning' },
  low: { label: 'Low', variant: 'secondary' },
} as const

const SPECIALIST: Record<string, string> = {
  health: 'Health agent',
  query: 'Query agent',
  schema: 'Schema agent',
}

/** Evidence ids such as T3 or Q12 in the answer become chips that show what the fact says. */
const EVIDENCE_REF = /\(?\b([HLTIQ]\d{1,3})\b\)?/g

function evidenceMap(findings: AgentFinding[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const f of findings) for (const e of f.evidence) map.set(e.id, e.summary)
  return map
}

function EvidenceChip({ id, summary }: { id: string; summary?: string }) {
  return (
    <span
      title={summary ?? id}
      className="mx-0.5 inline-flex items-center rounded border bg-muted px-1 font-mono text-[11px] leading-4 text-muted-foreground"
    >
      {id}
    </span>
  )
}

/** Plain text with `code` and evidence chips; nothing is rendered as HTML. */
function Inline({ text, evidence }: { text: string; evidence: Map<string, string> }) {
  const parts: ReactNode[] = []
  text.split(/(`[^`]+`)/).forEach((chunk, i) => {
    if (chunk.startsWith('`') && chunk.endsWith('`') && chunk.length > 2) {
      parts.push(
        <code key={i} className="rounded bg-muted px-1 font-mono text-[0.85em]">
          {chunk.slice(1, -1)}
        </code>,
      )
      return
    }
    let last = 0
    for (const m of chunk.matchAll(EVIDENCE_REF)) {
      const id = m[1]
      // A known fact id, or an id written in brackets as the answer is told to; not any "Q1".
      if (!evidence.has(id) && !m[0].startsWith('(')) continue
      parts.push(<Fragment key={`${i}-${last}`}>{chunk.slice(last, m.index)}</Fragment>)
      parts.push(<EvidenceChip key={`${i}-${m.index}`} id={id} summary={evidence.get(id)} />)
      last = (m.index ?? 0) + m[0].length
    }
    parts.push(<Fragment key={`${i}-end`}>{chunk.slice(last)}</Fragment>)
  })
  return <>{parts}</>
}

/** Paragraphs and "- " bullet lists from the model's plain-text answer. */
export function AnswerText({ text, evidence }: { text: string; evidence: Map<string, string> }) {
  const blocks = text.split(/\n\s*\n/).filter((b) => b.trim())
  return (
    <div className="grid gap-2 text-sm leading-relaxed">
      {blocks.map((block, i) => {
        const lines = block.split('\n').filter((l) => l.trim())
        if (lines.every((l) => /^\s*[-*•]\s+/.test(l)))
          return (
            <ul key={i} className="ml-4 list-disc space-y-1">
              {lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l.replace(/^\s*[-*•]\s+/, '')} evidence={evidence} />
                </li>
              ))}
            </ul>
          )
        return (
          <p key={i} className="whitespace-pre-line">
            <Inline text={block} evidence={evidence} />
          </p>
        )
      })}
    </div>
  )
}

function FindingCard({ f }: { f: AgentFinding }) {
  const sev = SEVERITY[f.severity]
  return (
    <li className="grid gap-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={sev.variant}>{sev.label}</Badge>
        <span className="text-xs text-muted-foreground">{SPECIALIST[f.specialist] ?? f.specialist}</span>
        {f.table && (
          <span className="inline-flex min-w-0 items-center gap-1 font-mono text-xs text-muted-foreground">
            <Table2 className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{f.table}</span>
          </span>
        )}
      </div>
      <p className="text-sm font-medium">{f.title}</p>
      <p className="text-sm text-muted-foreground">{f.explanation}</p>
      <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
        Evidence:
        {f.evidence.map((e) => (
          <EvidenceChip key={e.id} id={e.id} summary={e.summary} />
        ))}
      </p>
      {f.action && (
        <div className="grid gap-1.5">
          <CodeBlock code={f.action.statement} label={`Suggested fix · ${f.action.risk} risk`} />
          <p className="text-xs text-muted-foreground">
            {f.action.reason}. Checked by ZipZy, not run. Review it before running; approving and running from
            here comes in the next update.
          </p>
        </div>
      )}
    </li>
  )
}

function Steps({ run }: { run: AgentRun }) {
  const steps = run.steps.length ? run.steps : [{ key: 'queued', label: 'Starting' }]
  return (
    <ol className="grid gap-1.5 text-sm" aria-live="polite">
      {steps.map((s, i) => {
        const current = i === steps.length - 1
        return (
          <li key={`${s.key}-${i}`} className="flex items-center gap-2 text-muted-foreground">
            {current ? <Spinner className="size-3.5" /> : <Check className="size-3.5 text-success" aria-hidden />}
            <span className={current ? 'text-foreground' : undefined}>{s.label}…</span>
          </li>
        )
      })}
    </ol>
  )
}

export function RunView({
  run,
  onFollowUp,
  onChooseTable,
  onRetry,
  busy,
}: {
  run: AgentRun
  onFollowUp: (question: string) => void
  onChooseTable: (table: string) => void
  onRetry: () => void
  busy: boolean
}) {
  if (isActive(run)) return <Steps run={run} />

  if (run.status === 'failed')
    return (
      <Alert variant="destructive">
        <AlertTriangle aria-hidden />
        <AlertTitle>Could not answer</AlertTitle>
        <AlertDescription className="grid gap-2">
          <span>{run.error ?? 'Something went wrong.'}</span>
          <Button variant="outline" size="sm" className="w-fit" onClick={onRetry} disabled={busy}>
            <RotateCcw />
            Ask again
          </Button>
        </AlertDescription>
      </Alert>
    )

  const evidence = evidenceMap(run.findings)
  return (
    <div className="grid gap-3">
      {run.answer && <AnswerText text={run.answer} evidence={evidence} />}

      {run.clarification && (
        <div className="flex flex-wrap gap-2">
          {run.clarification.options.map((o) => (
            <Button key={o.table} variant="outline" size="sm" disabled={busy} onClick={() => onChooseTable(o.table)}>
              <Table2 />
              <span className="font-mono">{o.label}</span>
            </Button>
          ))}
        </div>
      )}

      {run.findings.length > 0 && (
        <ul className="grid gap-2">
          {run.findings.map((f) => (
            <FindingCard key={f.id} f={f} />
          ))}
        </ul>
      )}

      {run.notes.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="flex cursor-pointer list-none items-center gap-1 outline-none focus-visible:underline">
            <Info className="size-3.5" aria-hidden />
            {run.notes.length === 1 ? '1 note' : `${run.notes.length} notes`} about what was checked
          </summary>
          <ul className="mt-1 ml-5 list-disc space-y-0.5">
            {run.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}

      {run.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {run.follow_ups.map((q) => (
            <button
              key={q}
              type="button"
              disabled={busy}
              onClick={() => onFollowUp(q)}
              className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              <CircleDashed className="size-3" aria-hidden />
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
