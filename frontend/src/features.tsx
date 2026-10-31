import type { ReactNode } from 'react'
import { Activity, Bell, ClipboardList, TrendingUp, ChartColumnIncreasing, type LucideIcon } from 'lucide-react'
import { OrdersPage, InventoryPage, ForecastPage, ComparePage } from '@/pages/PlannerPage'
import { IntradayPage } from '@/pages/IntradayPage'
import { StatusPage } from '@/pages/StatusPage'

export interface Feature {path: string; label: string; icon: LucideIcon; element: ReactNode}
export const FEATURES: Feature[] = [
  {path:'/',label:'발주 추천',icon:ClipboardList,element:<OrdersPage/>},
  {path:'/inventory',label:'재고 알림',icon:Bell,element:<InventoryPage/>},
  {path:'/forecast',label:'수요 예측',icon:TrendingUp,element:<ForecastPage/>},
  {path:'/compare',label:'대안 비교·재고 이동',icon:ChartColumnIncreasing,element:<ComparePage/>},
  {path:'/intraday',label:'시간별 예측·재계획',icon:TrendingUp,element:<IntradayPage/>},
  {path:'/status',label:'연결 상태',icon:Activity,element:<StatusPage/>},
]
