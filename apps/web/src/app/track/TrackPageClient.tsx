'use client'

import { useState, useEffect, useCallback } from 'react'
import { Copy, CheckCircle2 } from 'lucide-react'
import { OtpInput } from '@/components/tracking/OtpInput'
import { OrderTimeline } from '@/components/checkout/OrderTimeline'
import type { OrderTimelineStep } from '@/components/checkout/OrderTimeline'
import { trackingApi, ApiError } from '@/lib/api'
import { COPY } from '@/lib/contract-copy'

type TrackPhase =
  | { step: 'ENTRY' }
  | { step: 'OTP_SENT';  maskedPhone: string; orderNumber: string }
  | { step: 'OTP_ERROR'; maskedPhone: string; orderNumber: string }
  | { step: 'ORDER_ACTIVE'; orderId: string; steps: OrderTimelineStep[]; carrierTrackNo: string }

const COOLDOWN_SECS = 30

export function TrackPageClient() {
  const [phase,      setPhase]      = useState<TrackPhase>({ step: 'ENTRY' })
  const [orderInput, setOrderInput] = useState('')
  const [touched,    setTouched]    = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [cooldown,   setCooldown]   = useState(0)
  const [copied,     setCopied]     = useState(false)
  const [otpKey,     setOtpKey]     = useState(0)

  // Tick only while cooldown is positive — avoids polling when idle
  const cooldownActive = cooldown > 0
  useEffect(() => {
    if (!cooldownActive) return
    const id = window.setInterval(() => setCooldown(c => Math.max(0, c - 1)), 1000)
    return () => window.clearInterval(id)
  }, [cooldownActive])

  const startCooldown = useCallback(() => setCooldown(COOLDOWN_SECS), [])

  const hasError = touched && orderInput.trim() === ''

  async function handleSendOtp(e?: React.FormEvent) {
    e?.preventDefault()
    setTouched(true)
    if (orderInput.trim() === '') return
    setLoading(true)
    try {
      const res = await trackingApi.sendOtp(orderInput.trim())
      setPhase({ step: 'OTP_SENT', maskedPhone: res.maskedPhone, orderNumber: orderInput.trim() })
      startCooldown()
    } finally {
      setLoading(false)
    }
  }

  async function handleVerifyOtp(code: string) {
    if (phase.step !== 'OTP_SENT' && phase.step !== 'OTP_ERROR') return
    const { maskedPhone, orderNumber: ord } = phase
    setLoading(true)
    try {
      const res = await trackingApi.verifyOtp(ord, code)
      setPhase({ step: 'ORDER_ACTIVE', orderId: res.orderId, steps: res.steps, carrierTrackNo: res.carrierTrackNo })
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setPhase({ step: 'OTP_ERROR', maskedPhone, orderNumber: ord })
      }
      setOtpKey(k => k + 1)
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    if (phase.step !== 'OTP_SENT' && phase.step !== 'OTP_ERROR') return
    const { orderNumber: ord } = phase
    setLoading(true)
    try {
      const res = await trackingApi.sendOtp(ord)
      setPhase({ step: 'OTP_SENT', maskedPhone: res.maskedPhone, orderNumber: ord })
      setOtpKey(k => k + 1)
      startCooldown()
    } finally {
      setLoading(false)
    }
  }

  function copyCarrierNo(no: string) {
    void navigator.clipboard.writeText(no)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // ─── ORDER_ACTIVE ────────────────────────────────────────────────────────
  if (phase.step === 'ORDER_ACTIVE') {
    return (
      <div className="max-w-[40rem] mx-auto px-4 sm:px-6">
        <section className="border border-gold/20 bg-surface rounded-sm p-5 sm:p-6">
          <p className="text-muted text-xs mb-0.5">{COPY.tracking.orderNumberLabel}</p>
          <p className="text-charcoal font-semibold tabular-nums mb-6" dir="ltr">
            {phase.orderId}
          </p>

          <OrderTimeline steps={phase.steps} />

          {/* Carrier tracking row */}
          <div className="mt-6 pt-5 border-t border-gold/10 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <p className="text-xs text-muted mb-0.5">{COPY.tracking.carrierTrackNo}</p>
              <p className="tabular-nums text-sm text-charcoal font-medium" dir="ltr">
                {phase.carrierTrackNo}
              </p>
            </div>
            <button
              onClick={() => copyCarrierNo(phase.carrierTrackNo)}
              className="flex items-center gap-1.5 text-xs border border-gold/30 rounded-sm px-3 py-1.5 text-muted hover:border-gold/50 transition-colors"
              aria-live="polite"
            >
              {copied ? (
                <>
                  <CheckCircle2 size={12} className="text-success" aria-hidden="true" />
                  {COPY.tracking.copied}
                </>
              ) : (
                <>
                  <Copy size={12} aria-hidden="true" />
                  {COPY.tracking.copy}
                </>
              )}
            </button>
          </div>
        </section>
      </div>
    )
  }

  // ─── OTP_SENT / OTP_ERROR ────────────────────────────────────────────────
  if (phase.step === 'OTP_SENT' || phase.step === 'OTP_ERROR') {
    return (
      <div className="max-w-[40rem] mx-auto px-4 sm:px-6">
        <section className="border border-gold/20 bg-surface rounded-sm p-5 sm:p-6">
          <h1 className="text-charcoal text-2xl font-semibold mb-2">
            {COPY.tracking.pageTitle}
          </h1>
          <p className="text-muted text-sm mb-6">
            {COPY.tracking.otpSentNote(phase.maskedPhone)}
          </p>

          <OtpInput key={otpKey} onComplete={handleVerifyOtp} />

          {phase.step === 'OTP_ERROR' && (
            <p className="text-error text-xs text-center mt-3" role="alert">
              {COPY.tracking.otpWrong}
            </p>
          )}

          {loading && (
            <p className="text-muted text-xs text-center mt-2" aria-live="polite">…</p>
          )}

          <div className="mt-5 text-center">
            {cooldown > 0 ? (
              <p className="text-muted text-xs tabular-nums">
                {COPY.tracking.otpResendAfter(cooldown)}
              </p>
            ) : (
              <button
                onClick={handleResend}
                disabled={loading}
                className="text-xs text-muted underline hover:text-charcoal disabled:opacity-40 transition-colors"
              >
                {COPY.tracking.otpResend}
              </button>
            )}
          </div>
        </section>
      </div>
    )
  }

  // ─── ENTRY ───────────────────────────────────────────────────────────────
  return (
    <div className="max-w-[40rem] mx-auto px-4 sm:px-6">
      <section className="border border-gold/20 bg-surface rounded-sm p-5 sm:p-6">
        <h1 className="text-charcoal text-2xl font-semibold mb-6">
          {COPY.tracking.pageTitle}
        </h1>
        <form onSubmit={handleSendOtp} noValidate>
          <label htmlFor="order-number" className="block text-xs font-medium text-charcoal mb-1.5">
            {COPY.tracking.orderNumberLabel}
          </label>
          <input
            id="order-number"
            dir="ltr"
            value={orderInput}
            onChange={e => setOrderInput(e.target.value)}
            onBlur={() => setTouched(true)}
            placeholder="ORD-5511"
            aria-invalid={hasError}
            aria-describedby={hasError ? 'order-error' : undefined}
            className={[
              'w-full border bg-surface rounded-sm px-3 py-2.5 text-sm text-charcoal tabular-nums',
              'focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold/30',
              hasError ? 'border-error' : 'border-gold/30',
            ].join(' ')}
          />
          {hasError && (
            <p id="order-error" className="text-error text-xs mt-1" role="alert">
              {COPY.checkout.errorRequired}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full mt-4 bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold tracking-wide hover:bg-bronze-hover transition-colors disabled:opacity-60"
          >
            {COPY.tracking.sendOtpCta}
          </button>
          <p className="text-muted text-xs mt-3">{COPY.tracking.otpHint}</p>
        </form>
      </section>
    </div>
  )
}
