import type { ReactNode } from "react";
import {
  LayoutDashboard,
  Bell,
  ClipboardList,
  TrendingUp,
  Warehouse,
  Truck,
  Activity,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "@/lib/auth";
import { InventoryPage, ForecastPage } from "@/pages/PlannerPage";
import { OverviewPage, SupplyPage } from "@/pages/OperationsPage";
import { IntradayPage } from "@/pages/IntradayPage";
import { StatusPage } from "@/pages/StatusPage";
export interface Feature {
  path: string;
  label: string;
  icon: LucideIcon;
  element: ReactNode;
  roles?: Role[];
}
export const FEATURES: Feature[] = [
  {
    path: "/",
    label: "운영 대시보드",
    icon: LayoutDashboard,
    element: <OverviewPage />,
  },
  {
    path: "/inventory",
    label: "재고·소비기한",
    icon: Bell,
    element: <InventoryPage />,
  },
  {
    path: "/orders",
    label: "정기발주",
    icon: ClipboardList,
    element: <SupplyPage view="orders" />,
  },
  {
    path: "/hub",
    label: "허브 공급",
    icon: Warehouse,
    element: <SupplyPage view="hub" />,
    roles: ["hub", "member"],
  },
  {
    path: "/emergency",
    label: "긴급발주",
    icon: Truck,
    element: <SupplyPage view="emergency" />,
  },
  {
    path: "/forecast",
    label: "수요 예측",
    icon: TrendingUp,
    element: <ForecastPage />,
  },
  {
    path: "/intraday",
    label: "시간별 수요",
    icon: TrendingUp,
    element: <IntradayPage forecastOnly />,
  },
  {
    path: "/status",
    label: "데이터 연결",
    icon: Activity,
    element: <StatusPage />,
  },
];
