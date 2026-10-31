// 백엔드와 주고받는 공통 타입. 기능이 정해지면 여기에 응답 타입을 추가한다.

export interface Scenario {
  as_of: string // 판단일 아침 (YYYY-MM-DD)
  store_id: string // S01 | S02 | S03
  horizon_days: number // 1~14
  demand_multiplier: number // 수요 배율 k
  delay_days: number // 입고 지연 (가상 시나리오)
  service_level: number | null // null = 품목별 자동
}

export interface HealthResponse {
  ok: boolean
  tables: Record<string, number>
}

export interface ApiErrorBody {
  error: { code: string; message: string }
}
