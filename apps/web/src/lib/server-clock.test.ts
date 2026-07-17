import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createServerClock, cntFmt, RESERVATION_MS, syncServerClock, serverNow } from './server-clock'

describe('createServerClock', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns server time when device clock matches', () => {
    const serverNow = '2026-01-01T12:00:00.000Z'
    vi.setSystemTime(new Date(serverNow))
    const clock = createServerClock(serverNow)
    expect(clock.now().toISOString()).toBe(serverNow)
  })

  it('corrects device clock that is +3h ahead of real time', () => {
    const realServerNow = new Date('2026-01-01T12:00:00.000Z')
    // Device thinks it's 3 hours ahead
    vi.setSystemTime(new Date('2026-01-01T15:00:00.000Z'))

    const clock = createServerClock(realServerNow.toISOString())
    // clock.now() should return server time (12:00), not device time (15:00)
    expect(clock.now().toISOString()).toBe(realServerNow.toISOString())
  })

  it('corrects device clock that is -1h behind real time', () => {
    const realServerNow = new Date('2026-01-01T12:00:00.000Z')
    vi.setSystemTime(new Date('2026-01-01T11:00:00.000Z'))

    const clock = createServerClock(realServerNow.toISOString())
    expect(clock.now().toISOString()).toBe(realServerNow.toISOString())
  })

  it('advances with device time after anchoring', () => {
    const serverNow = '2026-01-01T12:00:00.000Z'
    vi.setSystemTime(new Date('2026-01-01T15:00:00.000Z')) // device +3h
    const clock = createServerClock(serverNow)

    // Advance device time by 60s
    vi.advanceTimersByTime(60_000)

    const expected = new Date('2026-01-01T12:01:00.000Z')
    expect(clock.now().toISOString()).toBe(expected.toISOString())
  })

  it('update() re-anchors to a new server timestamp', () => {
    const serverNow = '2026-01-01T12:00:00.000Z'
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'))
    const clock = createServerClock(serverNow)

    // A new response arrives with a server timestamp 5 minutes later
    vi.advanceTimersByTime(5 * 60_000)
    clock.update('2026-01-01T12:05:00.000Z')

    expect(clock.now().toISOString()).toBe('2026-01-01T12:05:00.000Z')
  })
})

describe('cntFmt', () => {
  it('formats 10 minutes as 10:00', () => {
    expect(cntFmt(10 * 60 * 1000)).toBe('10:00')
  })

  it('formats 90 seconds as 01:30', () => {
    expect(cntFmt(90_000)).toBe('01:30')
  })

  it('formats 0 ms as 00:00', () => {
    expect(cntFmt(0)).toBe('00:00')
  })

  it('clamps negative ms to 00:00', () => {
    expect(cntFmt(-5000)).toBe('00:00')
  })

  it('pads single-digit seconds', () => {
    expect(cntFmt(61_000)).toBe('01:01')
  })
})

describe('RESERVATION_MS', () => {
  it('is 10 minutes in milliseconds', () => {
    expect(RESERVATION_MS).toBe(600_000)
  })
})

describe('module singleton (serverNow / syncServerClock)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('returns corrected time after sync', () => {
    vi.setSystemTime(new Date('2026-01-01T15:00:00.000Z')) // device +3h
    syncServerClock('2026-01-01T12:00:00.000Z')
    expect(serverNow()).toBe(new Date('2026-01-01T12:00:00.000Z').getTime())
  })
})
