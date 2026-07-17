// R1 — Domain is the source of truth.
// UI reflects these states ONLY. No component computes business state from local
// conditions — goldStatusFromAge and siblings live here, nowhere else.
// Mirror of backend Domain enums; temporary until generated from packages/contracts.

export enum GoldPriceStatus {
  FRESH  = 'FRESH',
  STALE  = 'STALE',
  HALTED = 'HALTED',
}

export enum ItemAvailability {
  AVAILABLE = 'AVAILABLE',
  RESERVED = 'RESERVED',
  SOLD = 'SOLD',
}

export enum ReservationStatus {
  ACTIVE = 'ACTIVE',
  CONFIRMED = 'CONFIRMED',
  EXPIRED = 'EXPIRED',
  CANCELLED = 'CANCELLED',
}

export enum PaymentStatus {
  PENDING = 'PENDING',
  PAID = 'PAID',
  FAILED = 'FAILED',
  REFUND_PENDING = 'REFUND_PENDING',
  REFUNDED = 'REFUNDED',
}

export enum OrderStatus {
  PAID             = 'PAID',
  PREPARING        = 'PREPARING',
  SHIPMENT_CREATED = 'SHIPMENT_CREATED',
  SHIPPED          = 'SHIPPED',
  DELIVERED        = 'DELIVERED',
  CANCELLED        = 'CANCELLED',
}

/**
 * FC-6 — Freshness derives from age alone regardless of cause.
 * Provider outage, network loss, manual halt — all collapse to HALTED.
 * Threshold: ≤90 s → FRESH, >90 s → STALE, halted flag → HALTED.
 * Components call this; they never recompute the threshold themselves.
 */
export function goldStatusFromAge(
  ageSeconds: number,
  halted = false,
): GoldPriceStatus {
  if (halted) return GoldPriceStatus.HALTED
  return ageSeconds > 90 ? GoldPriceStatus.STALE : GoldPriceStatus.FRESH
}
