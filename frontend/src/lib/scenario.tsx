// 사이드바 시나리오 입력을 모든 화면이 공유한다.
// 화면에서 useScenario()로 읽고, React Query의 queryKey에 scenario를 넣으면
// 입력이 바뀔 때 자동으로 다시 요청된다.
import { createContext, useContext, useState, type ReactNode } from 'react'
import type { Scenario } from '@/types/api'

export const DEFAULT_SCENARIO: Scenario = {
  as_of: '2026-10-01',
  store_id: 'S01',
  horizon_days: 7,
  demand_multiplier: 1,
  delay_days: 0,
  service_level: 0.90,
  transfer_minutes: 30,
  transfer_cost: 100,
  can_split_pack: true,
}

export const DATE_RANGE = { min: '2026-07-01', max: '2026-10-01' }
export const STORES = [
  { id: 'S01', name: '가상매장 A' },
  { id: 'S02', name: '가상매장 B' },
  { id: 'S03', name: '가상매장 C' },
]

interface Ctx {
  scenario: Scenario
  update: (patch: Partial<Scenario>) => void
  reset: () => void
}

const ScenarioContext = createContext<Ctx | null>(null)

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [scenario, setScenario] = useState<Scenario>(DEFAULT_SCENARIO)
  const update = (patch: Partial<Scenario>) => setScenario((s) => ({ ...s, ...patch }))
  const reset = () => setScenario(DEFAULT_SCENARIO)
  return <ScenarioContext.Provider value={{ scenario, update, reset }}>{children}</ScenarioContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useScenario() {
  const ctx = useContext(ScenarioContext)
  if (!ctx) throw new Error('useScenario는 ScenarioProvider 안에서 써야 합니다')
  return ctx
}
