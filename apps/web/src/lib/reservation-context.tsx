'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

export interface ActiveReservation {
  reservationId: string
  expiresAt:     string
}

interface ReservationCtxValue {
  reservations:      ActiveReservation[]
  addReservation:    (r: ActiveReservation) => void
  removeReservation: (id: string) => void
}

const ReservationCtx = createContext<ReservationCtxValue>({
  reservations:      [],
  addReservation:    () => {},
  removeReservation: () => {},
})

export const useReservation = () => useContext(ReservationCtx)

export function ReservationProvider({ children }: { children: ReactNode }) {
  const [reservations, setReservations] = useState<ActiveReservation[]>([])

  const addReservation = useCallback((r: ActiveReservation) => {
    setReservations(prev => [
      ...prev.filter(x => x.reservationId !== r.reservationId),
      r,
    ])
  }, [])

  const removeReservation = useCallback((id: string) => {
    setReservations(prev => prev.filter(x => x.reservationId !== id))
  }, [])

  return (
    <ReservationCtx.Provider value={{ reservations, addReservation, removeReservation }}>
      {children}
    </ReservationCtx.Provider>
  )
}
