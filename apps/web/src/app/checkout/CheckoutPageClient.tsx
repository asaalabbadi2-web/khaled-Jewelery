'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useSearchParams } from 'next/navigation'
import { Lock, CheckCircle } from 'lucide-react'
import { ReservationStrip } from '@/components/checkout/ReservationStrip'
import { OrderTimeline } from '@/components/checkout/OrderTimeline'
import { COPY } from '@/lib/contract-copy'
import { BRAND_NAME } from '@/lib/brand'
import { pr } from '@/lib/format'
import { RESERVATION_MS } from '@/lib/server-clock'

// ─── Types ─────────────────────────────────────────────────────────────────

interface AddressData {
  name:     string
  phone:    string
  email:    string
  city:     string
  district: string
  address:  string
  notes:    string
}

type FormErrors = Partial<Record<keyof AddressData, string>>

type CheckoutPhase =
  | { step: 'ADDRESS' }
  | { step: 'PAYMENT';     address: AddressData }
  | { step: 'REDIRECTING'; address: AddressData }
  | { step: 'VERIFYING';   address: AddressData }
  | { step: 'SUCCESS';     address: AddressData; orderId: string }
  | { step: 'EXPIRED' }

// ─── Validation ────────────────────────────────────────────────────────────

const REQUIRED_FIELDS: (keyof AddressData)[] = ['name', 'phone', 'city', 'district', 'address']

function validateAddress(data: AddressData): FormErrors {
  const errors: FormErrors = {}
  for (const field of REQUIRED_FIELDS) {
    if (!data[field].trim()) errors[field] = COPY.checkout.errorRequired
  }
  if (data.phone && !/^05\d{8}$/.test(data.phone.replace(/\s/g, ''))) {
    errors.phone = COPY.checkout.errorPhone
  }
  return errors
}

// ─── Summary column ────────────────────────────────────────────────────────

function CheckoutSummary({ name, price }: { name: string; price: number }) {
  return (
    <aside className="bg-surface border border-gold/20 rounded-sm p-5 flex flex-col gap-4">
      <p className="text-charcoal font-semibold text-sm">{name}</p>
      <div className="border-t border-gold/10 pt-4 flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1 text-muted text-xs">
            <Lock size={11} className="text-gold" aria-hidden="true" />
            {COPY.checkout.lockedTotal}
          </span>
          <span className="flex items-baseline gap-1">
            <span dir="ltr" className="tabular-nums text-charcoal font-semibold">{pr(price)}</span>
            <span className="text-muted text-xs">{COPY.pricing.priceUnit}</span>
          </span>
        </div>
        <p className="text-muted text-xs">{COPY.checkout.priceFixed}</p>
      </div>
    </aside>
  )
}

// ─── Step indicator ────────────────────────────────────────────────────────

function StepIndicator({ step }: { step: 1 | 2 }) {
  return (
    <div className="flex items-center gap-2 mb-6" aria-label={COPY.checkout.stepAriaLabel(step)}>
      {([1, 2] as const).map(n => (
        <div key={n} className="flex items-center gap-2">
          <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
            n < step  ? 'bg-success text-surface' :
            n === step ? 'border-2 border-gold text-gold' :
                         'border border-muted/30 text-muted-2'
          }`}>
            {n < step ? '✓' : n}
          </span>
          <span className={`text-xs ${n === step ? 'text-charcoal font-medium' : 'text-muted'}`}>
            {n === 1 ? COPY.checkout.step1Label : COPY.checkout.step2Label}
          </span>
          {n === 1 && <span className="text-muted/40 mx-1">{'›'}</span>}
        </div>
      ))}
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────────────────

export function CheckoutPageClient() {
  const router       = useRouter()
  const searchParams = useSearchParams()

  const expiresAt = searchParams.get('expiresAt') ?? ''
  const price     = parseFloat(searchParams.get('price') ?? '0')
  const itemName  = searchParams.get('name') ?? 'القطعة المحجوزة'

  // Local countdown — no GoldPriceProvider needed (price is locked)
  const [ms, setMs] = useState(() =>
    expiresAt ? Math.max(0, new Date(expiresAt).getTime() - Date.now()) : 0
  )
  useEffect(() => {
    const id = window.setInterval(
      () => setMs(expiresAt ? Math.max(0, new Date(expiresAt).getTime() - Date.now()) : 0),
      500,
    )
    return () => window.clearInterval(id)
  }, [expiresAt])

  const [phase,   setPhase]   = useState<CheckoutPhase>({ step: 'ADDRESS' })
  const [form,    setForm]    = useState<AddressData>({ name: '', phone: '', email: '', city: '', district: '', address: '', notes: '' })
  const [errors,  setErrors]  = useState<FormErrors>({})
  const [touched, setTouched] = useState<Set<keyof AddressData>>(new Set())
  const formRef = useRef<HTMLFormElement>(null)

  // EXPIRED transition — fires once when ms hits 0 during ADDRESS or PAYMENT steps
  useEffect(() => {
    if (ms === 0 && (phase.step === 'ADDRESS' || phase.step === 'PAYMENT')) {
      setPhase({ step: 'EXPIRED' })
    }
  }, [ms, phase.step])

  const handleBlur = useCallback((field: keyof AddressData) => {
    setTouched(prev => new Set(prev).add(field))
    const errs = validateAddress(form)
    setErrors(prev => ({ ...prev, [field]: errs[field] }))
  }, [form])

  const handleChange = useCallback((field: keyof AddressData, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }))
    if (touched.has(field)) {
      const errs = validateAddress({ ...form, [field]: value })
      setErrors(prev => ({ ...prev, [field]: errs[field] }))
    }
  }, [form, touched])

  const handleStep1Submit = useCallback(() => {
    const allTouched = new Set(REQUIRED_FIELDS) as Set<keyof AddressData>
    setTouched(allTouched)
    const errs = validateAddress(form)
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      // Scroll to first error
      formRef.current?.querySelector('[aria-invalid="true"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    setPhase({ step: 'PAYMENT', address: form })
  }, [form])

  const handlePaymentCta = useCallback(() => {
    if (phase.step !== 'PAYMENT') return
    const addr = phase.address
    setPhase({ step: 'REDIRECTING', address: addr })
    // Mock redirect delay → verifying
    setTimeout(() => setPhase({ step: 'VERIFYING', address: addr }), 1_800)
    // Mock verify delay → success
    setTimeout(() => setPhase({ step: 'SUCCESS', address: addr, orderId: COPY.checkout.successOrderId }), 3_500)
  }, [phase])

  const goBack = useCallback(() => {
    if (phase.step === 'PAYMENT') setPhase({ step: 'ADDRESS' })
  }, [phase])

  const isActive = phase.step !== 'EXPIRED' && phase.step !== 'SUCCESS' && phase.step !== 'VERIFYING' && phase.step !== 'REDIRECTING'
  const showSummary = phase.step === 'ADDRESS' || phase.step === 'PAYMENT'

  // ─── CHROME ──────────────────────────────────────────────────────────────

  const header = (
    <header className="fixed top-0 inset-x-0 h-10 z-50 bg-charcoal flex items-center justify-between px-5">
      <span className="text-ivory font-semibold text-sm">{BRAND_NAME}</span>
      <span className="flex items-center gap-1.5 text-muted text-xs">
        <Lock size={11} aria-hidden="true" />
        {COPY.checkout.securePayment}
      </span>
    </header>
  )

  const strip = isActive
    ? <ReservationStrip ms={ms} reservationMs={RESERVATION_MS} />
    : null

  // Content top padding: header(40px) + strip(45px) = 85px when strip shows; 40px otherwise
  const ptClass = isActive ? 'pt-[85px]' : 'pt-[52px]'

  // ─── REDIRECTING ─────────────────────────────────────────────────────────

  if (phase.step === 'REDIRECTING' || phase.step === 'VERIFYING') {
    const isVerifying = phase.step === 'VERIFYING'
    return (
      <>
        {header}
        {strip}
        <div className={`${ptClass} min-h-screen flex flex-col items-center justify-center gap-4 px-4`}>
          <div
            className="w-10 h-10 rounded-full border-2 border-gold/20 border-t-gold animate-spin"
            aria-hidden="true"
          />
          <p className="text-charcoal font-semibold text-center">
            {isVerifying ? COPY.checkout.verifyingTitle : COPY.checkout.redirectingTitle}
          </p>
          <p className="text-muted text-xs text-center max-w-xs leading-relaxed">
            {isVerifying ? COPY.checkout.verifyingNote : COPY.checkout.redirectingNote}
          </p>
        </div>
      </>
    )
  }

  // ─── SUCCESS ─────────────────────────────────────────────────────────────

  if (phase.step === 'SUCCESS') {
    const successSteps = [
      { label: COPY.timeline.paid,          done: true,  active: false },
      { label: COPY.timeline.preparing,     done: false, active: true  },
      { label: COPY.timeline.shipmentReady, done: false, active: false },
      { label: COPY.timeline.shipped,       done: false, active: false },
      { label: COPY.timeline.delivered,     done: false, active: false },
    ]
    return (
      <>
        {header}
        <div className="pt-[52px] min-h-screen flex flex-col items-center justify-start px-4 py-10">
          <div className="w-full max-w-md">
            <div className="flex items-center gap-3 mb-5">
              <span className="w-9 h-9 rounded-full bg-success/10 flex items-center justify-center shrink-0">
                <CheckCircle size={20} className="text-success" aria-hidden="true" />
              </span>
              <div>
                <p className="text-charcoal font-semibold">{COPY.checkout.successTitle}</p>
                <p className="text-muted text-xs mt-0.5">{COPY.checkout.successNote}</p>
              </div>
            </div>

            <div className="border border-gold/20 rounded-sm p-5 mb-5 bg-surface">
              <p className="text-xs text-muted mb-1">{COPY.checkout.orderIdLabel}</p>
              <p className="text-charcoal font-semibold tabular-nums" dir="ltr">{phase.orderId}</p>
              <div className="mt-5">
                <OrderTimeline steps={successSteps} />
              </div>
            </div>

            <button
              onClick={() => router.push('/track')}
              className="w-full bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors mb-3"
            >
              {COPY.checkout.trackCta}
            </button>
            <button
              onClick={() => router.push('/jewellery/rings')}
              className="w-full border border-gold/30 text-muted py-3 rounded-sm text-sm hover:border-gold/50 transition-colors"
            >
              {COPY.checkout.backToCatalog}
            </button>
          </div>
        </div>
      </>
    )
  }

  // ─── EXPIRED IN CHECKOUT ─────────────────────────────────────────────────

  if (phase.step === 'EXPIRED') {
    const newPrice = Math.round((price * 1.005) / 0.5) * 0.5 // mock: slight fluctuation
    return (
      <>
        {header}
        <div className="pt-[52px] min-h-screen flex flex-col items-center justify-start px-4 py-10">
          <div className="w-full max-w-md border border-muted/30 rounded-sm p-5 bg-surface">
            <p className="text-charcoal font-semibold mb-1">{COPY.checkout.expiredTitle}</p>
            <p className="text-success text-xs mb-5">{COPY.checkout.expiredDataSaved}</p>

            <div className="flex flex-col gap-2 border border-gold/15 rounded-sm p-3 mb-5 text-sm">
              <div className="flex justify-between">
                <span className="text-muted">{COPY.pricing.prevPrice}</span>
                <span dir="ltr" className="tabular-nums text-muted">{pr(price)} {COPY.pricing.priceUnit}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-charcoal font-medium">{COPY.pricing.newPrice}</span>
                <span dir="ltr" className="tabular-nums text-charcoal font-medium">{pr(newPrice)} {COPY.pricing.priceUnit}</span>
              </div>
            </div>

            <button
              onClick={() => router.back()}
              className="w-full bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors mb-3"
            >
              {COPY.checkout.expiredRebookCta}
            </button>
            <button
              onClick={() => router.back()}
              className="w-full text-muted text-xs underline"
            >
              {COPY.checkout.expiredBackCta}
            </button>
          </div>
        </div>
      </>
    )
  }

  // ─── Field component ─────────────────────────────────────────────────────

  function Field({
    id, label, required, error, children,
  }: { id: string; label: string; required?: boolean; error?: string; children: React.ReactNode }) {
    return (
      <div>
        <label htmlFor={id} className="block text-xs font-medium text-charcoal mb-1">
          {label}{required && <span className="text-gold mr-0.5">*</span>}
        </label>
        {children}
        {error && (
          <p className="text-xs text-warning mt-1" role="alert">{error}</p>
        )}
      </div>
    )
  }

  const inputCls = (field: keyof AddressData) =>
    `w-full border rounded-sm px-3 py-2.5 text-sm text-charcoal bg-surface focus:outline-none focus:ring-1 focus:ring-gold/30 ${
      errors[field] ? 'border-warning focus:border-warning' : 'border-gold/30 focus:border-gold'
    }`

  // ─── STEP 1 — ADDRESS ────────────────────────────────────────────────────

  const step1Content = (
    <div className="w-full">
      <StepIndicator step={1} />
      <p className="text-charcoal font-semibold mb-5">{COPY.checkout.addressSectionTitle}</p>

      <form ref={formRef} onSubmit={e => { e.preventDefault(); handleStep1Submit() }} noValidate>
        <div className="flex flex-col gap-4">
          <Field id="name" label={COPY.checkout.fieldName} required error={touched.has('name') ? errors.name : undefined}>
            <input
              id="name"
              value={form.name}
              onChange={e => handleChange('name', e.target.value)}
              onBlur={() => handleBlur('name')}
              aria-invalid={touched.has('name') && !!errors.name}
              className={inputCls('name')}
            />
          </Field>

          <Field id="phone" label={COPY.checkout.fieldPhone} required error={touched.has('phone') ? errors.phone : undefined}>
            <div className="flex gap-2">
              <span className="border border-gold/30 bg-ivory rounded-sm px-3 py-2.5 text-sm text-muted shrink-0">
                {COPY.checkout.securePayment.includes('دفع') ? '+966' : '+966'}
              </span>
              <input
                id="phone"
                type="tel"
                inputMode="numeric"
                placeholder="05xxxxxxxx"
                dir="ltr"
                value={form.phone}
                onChange={e => handleChange('phone', e.target.value)}
                onBlur={() => handleBlur('phone')}
                aria-invalid={touched.has('phone') && !!errors.phone}
                className={`flex-1 ${inputCls('phone')}`}
              />
            </div>
            <p className="text-muted text-[11px] mt-1">{COPY.checkout.phoneHint}</p>
          </Field>

          <Field id="email" label={COPY.checkout.fieldEmail} error={undefined}>
            <input
              id="email"
              type="email"
              value={form.email}
              onChange={e => handleChange('email', e.target.value)}
              className={inputCls('email')}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field id="city" label={COPY.checkout.fieldCity} required error={touched.has('city') ? errors.city : undefined}>
              <input
                id="city"
                value={form.city}
                onChange={e => handleChange('city', e.target.value)}
                onBlur={() => handleBlur('city')}
                aria-invalid={touched.has('city') && !!errors.city}
                className={inputCls('city')}
              />
            </Field>
            <Field id="district" label={COPY.checkout.fieldDistrict} required error={touched.has('district') ? errors.district : undefined}>
              <input
                id="district"
                value={form.district}
                onChange={e => handleChange('district', e.target.value)}
                onBlur={() => handleBlur('district')}
                aria-invalid={touched.has('district') && !!errors.district}
                className={inputCls('district')}
              />
            </Field>
          </div>

          <Field id="address-detail" label={COPY.checkout.fieldAddress} required error={touched.has('address') ? errors.address : undefined}>
            <textarea
              id="address-detail"
              rows={2}
              value={form.address}
              onChange={e => handleChange('address', e.target.value)}
              onBlur={() => handleBlur('address')}
              aria-invalid={touched.has('address') && !!errors.address}
              className={`resize-none ${inputCls('address')}`}
            />
          </Field>

          <Field id="notes" label={COPY.checkout.fieldNotes} error={undefined}>
            <textarea
              id="notes"
              rows={2}
              value={form.notes}
              onChange={e => handleChange('notes', e.target.value)}
              className={`resize-none ${inputCls('notes')}`}
            />
          </Field>

          <p className="text-muted text-xs">{COPY.checkout.deliveryNote}</p>

          <button
            type="submit"
            className="w-full bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
          >
            {COPY.checkout.step1Cta}
          </button>
        </div>
      </form>
    </div>
  )

  // ─── STEP 2 — PAYMENT ────────────────────────────────────────────────────

  const step2Content = phase.step === 'PAYMENT' ? (
    <div className="w-full">
      <StepIndicator step={2} />

      {/* Address summary */}
      <div className="border border-gold/20 rounded-sm p-4 mb-5 bg-ivory/40">
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm text-charcoal leading-relaxed">
            <p>{phase.address.name}</p>
            <p dir="ltr" className="text-muted">{phase.address.phone}</p>
            <p className="text-muted">{phase.address.city}، {phase.address.district}</p>
            <p className="text-muted">{phase.address.address}</p>
          </div>
          <button
            onClick={goBack}
            className="text-xs text-muted underline hover:text-charcoal shrink-0"
          >
            {COPY.checkout.editAddress}
          </button>
        </div>
      </div>

      {/* Payment marks */}
      <div className="mb-5">
        <p className="text-xs font-medium text-charcoal mb-3">{COPY.checkout.paymentMethods}</p>
        <div className="flex flex-wrap gap-2">
          {['mada', 'Apple Pay', 'Visa', 'Mastercard'].map(mark => (
            <span
              key={mark}
              className="border border-muted/20 rounded-sm px-2.5 py-1 text-xs text-muted bg-surface"
            >
              {mark}
            </span>
          ))}
        </div>
      </div>

      <button
        onClick={handlePaymentCta}
        className="w-full bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors mb-3"
      >
        {COPY.checkout.paymentCta}
      </button>
      <p className="text-muted text-xs text-center mb-4">{COPY.checkout.paymentNoCard}</p>
      <p className="text-muted text-xs text-center mb-4">{COPY.checkout.paymentNote}</p>

      <div className="text-center">
        <button
          onClick={() => router.back()}
          className="text-muted text-xs underline hover:text-charcoal"
        >
          {COPY.checkout.cancelLink}
        </button>
      </div>
    </div>
  ) : null

  // ─── LAYOUT ──────────────────────────────────────────────────────────────

  return (
    <>
      {header}
      {strip}
      <div className={`${ptClass} max-w-4xl mx-auto px-4 sm:px-6 pb-16`}>
        <div className={`${showSummary ? 'grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8 lg:gap-12' : ''} pt-8`}>

          {/* Left: step content */}
          {phase.step === 'ADDRESS' && step1Content}
          {phase.step === 'PAYMENT' && step2Content}

          {/* Right: summary (steps 1 + 2 only) */}
          {showSummary && (
            <CheckoutSummary name={itemName} price={price} />
          )}
        </div>
      </div>
    </>
  )
}
