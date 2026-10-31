// 화면 목록. 기능을 추가·삭제·이름 변경할 때는 이 배열만 고친다.
// (사이드바 메뉴와 라우팅이 이 목록에서 자동 생성됨)
import type { ReactNode } from 'react'
import { Activity, Bell, ClipboardList, TrendingUp, type LucideIcon } from 'lucide-react'
import { Placeholder } from '@/pages/Placeholder'
import { StatusPage } from '@/pages/StatusPage'

export interface Feature {
  path: string
  label: string
  icon: LucideIcon
  element: ReactNode
}

export const FEATURES: Feature[] = [
  {
    path: '/',
    label: '발주 추천',
    icon: ClipboardList,
    element: <Placeholder title="발주 추천" description="공급사 조건을 반영한 오늘의 발주서" />,
  },
  {
    path: '/inventory',
    label: '재고 알림',
    icon: Bell,
    element: <Placeholder title="재고 알림" description="부족·만료·과잉 재고 알림" />,
  },
  {
    path: '/forecast',
    label: '수요 예측',
    icon: TrendingUp,
    element: <Placeholder title="수요 예측" description="메뉴별 수요와 식자재 필요량" />,
  },
  { path: '/status', label: '연결 상태', icon: Activity, element: <StatusPage /> },
]
