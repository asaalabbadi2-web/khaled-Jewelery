interface DividerProps {
  /** Tailwind opacity fraction, default '/15' (matches gold border pattern throughout) */
  opacity?: '/10' | '/15' | '/20' | '/25'
  className?: string
}

export function Divider({ opacity = '/15', className = '' }: DividerProps) {
  return (
    <div
      className={`border-t border-gold${opacity} ${className}`}
      role="separator"
      aria-hidden="true"
    />
  )
}
