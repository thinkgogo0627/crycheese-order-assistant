// VITE_USE_MOCK=true 일 때 쓰는 더미 응답. 경로 → 응답 데이터.
// 백엔드가 준비되기 전에 화면을 먼저 만들 때 사용한다.
import type { HealthResponse } from '@/types/api'

export const MOCKS: Record<string, unknown> = {
  '/health': {
    ok: true,
    tables: { '01_stores': 3, '02_menus': 16, '03_ingredients': 22, '09_sales': 98910 },
  } satisfies HealthResponse,
}
