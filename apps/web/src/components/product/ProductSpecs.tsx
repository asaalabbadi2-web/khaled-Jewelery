export interface ProductSpecsProps {
  karat: 18 | 21 | 22 | 24
  weight: number
}

export function ProductSpecs({ karat, weight }: ProductSpecsProps) {
  return (
    <p className="text-muted text-xs mt-0.5">
      <span dir="ltr" className="tabular-nums">{karat}K</span>
      {' · '}
      <span dir="ltr" className="tabular-nums">{weight.toFixed(2)}</span>
      {'غ'}
    </p>
  )
}
