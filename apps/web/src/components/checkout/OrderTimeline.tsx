import { COPY } from '@/lib/contract-copy'

export interface OrderTimelineStep {
  label: string
  done: boolean
  active: boolean
}

export interface OrderTimelineProps {
  steps: OrderTimelineStep[]
  className?: string
}

export function OrderTimeline({ steps, className = '' }: OrderTimelineProps) {
  return (
    <ol
      className={`text-right ${className}`}
      aria-label={COPY.timeline.ariaLabel}
    >
      {steps.map(({ label, done, active }, i) => (
        <li
          key={label}
          className="flex items-start gap-3 mb-0"
          aria-current={active ? 'step' : undefined}
        >
          {/* Step indicator */}
          <div className="flex flex-col items-center shrink-0">
            <div
              className={[
                'w-5 h-5 rounded-full flex items-center justify-center mt-0.5',
                done   ? 'bg-success' :
                active ? 'border-2 border-gold bg-surface' :
                         'border border-muted/30 bg-surface',
              ].join(' ')}
              aria-hidden="true"
            >
              {done   && <span className="text-surface text-[8px] font-bold">✓</span>}
              {active && <span className="w-2 h-2 rounded-full bg-gold animate-pulse block" />}
            </div>

            {/* Connector line */}
            {i < steps.length - 1 && (
              <div
                className={`w-px h-5 mt-0.5 ${done ? 'bg-success/40' : 'bg-muted/30'}`}
              />
            )}
          </div>

          <p className={`text-sm pt-0.5 ${done || active ? 'text-charcoal' : 'text-muted-2'}`}>
            {label}
          </p>
        </li>
      ))}
    </ol>
  )
}
