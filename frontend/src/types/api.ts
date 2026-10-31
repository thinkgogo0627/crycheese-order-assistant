export interface Scenario {
  as_of: string;
  store_id: string;
  horizon_days: number;
  demand_multiplier: number;
  delay_days: number;
  service_level: number | null;
  transfer_minutes: number;
  transfer_cost: number;
  can_split_pack: boolean;
  forecast_profile?: "original" | "balanced" | "protective";
  decision_time?: string;
  horizon_hours?: number;
  promotion_multiplier?: number;
  adjustment_strength?: number | null;
  minimum_avoided_menu_qty?: number;
  live_sales?: { store_id: string; menu_id: string; hour: number; sold_qty: number }[] | null;
  hub_store_ids?: string[];
  hub_host_store_id?: string | null;
  hub_policy?: "auto" | "assigned" | "none";
  max_hubs?: number;
  chilled_capacity_liters?: number;
  frozen_capacity_liters?: number;
  ambient_capacity_liters?: number;
  hub_daily_cost?: number;
}

export interface HealthResponse {
  ok: boolean;
  tables: Record<string, number>;
}
export interface ApiErrorBody {
  error?: { code: string; message: string };
  detail?: string;
}
export interface ForecastItem {
  menu_id: string;
  menu: string;
  qty: number;
  price: number;
}
export interface IngredientItem {
  ingredient_id: string;
  ingredient: string;
  unit: string;
  predicted_today: number;
  current_stock: number;
  opening_stock?: number;
  received_today?: number;
  inventory_basis?: string;
  expiry_nearest: string | null;
}
export interface OrderLine {
  supplier_id: string;
  supplier: string;
  store_id: string;
  ingredient_id: string;
  ingredient: string;
  order_date: string;
  arrival_date: string;
  order_qty: number;
  order_unit: string;
  use_qty: number;
  amount: number;
  allocated: Record<string, number>;
  unit?: string;
  reason?: string;
}
export interface TransferLine {
  ingredient_id: string;
  ingredient: string;
  qty: number;
  unit: string;
  estimated_food_value: number;
}
export interface TransferRoute {
  from_store: string;
  to_store: string;
  depart: string;
  arrive: string;
  minutes: number;
  trip_cost: number;
  items: TransferLine[];
  estimated_food_value: number;
}
export interface LotProjection {
  lot_id: string;
  receipt_date: string;
  last_use_date: string;
  current_qty: number;
  expected_used_qty: number;
  expected_expiry_qty: number;
}
export interface Alert {
  type: string;
  store: string;
  item: string;
  name: string;
  qty: number;
  unit: string;
  date: string;
  detail?: string;
  expiring_qty?: number;
  expected_use_before_expiry_qty?: number;
  expected_expiry_qty?: number;
  expected_expiry_cost?: number;
  lots?: LotProjection[];
}
export interface PlanComparison {
  mode: string;
  purchase_cost: number;
  transport_cost: number;
  waste_cost: number;
  expected_revenue: number;
  lost_qty: number;
  fill_rate: number;
  ordered_packs: number;
  trip_count: number;
  closing_value: number;
  contribution_after_waste_and_transport: number;
}
export interface Blocked {
  date: string;
  supplier: string;
  store: string;
  amount: number;
  minimum: number;
  reason: string;
  action?: string;
}
export interface PlanResponse {
  as_of: string;
  store_id: string;
  recommended_mode: string;
  service_target: number;
  forecast: ForecastItem[];
  ingredients: IngredientItem[];
  comparison: PlanComparison[];
  orders: OrderLine[];
  all_orders: OrderLine[];
  transfers: TransferRoute[];
  shared_alternative_transfers: TransferRoute[];
  alerts: Alert[];
  all_alerts: Alert[];
  blocked: Blocked[];
  data_issues: string[];
  assumptions: string[];
}

export interface HubOrder {
  store_id: string;
  ingredient_id: string;
  ingredient_name: string;
  supplier_id: string;
  order_date: string;
  arrival_date: string;
  order_qty: number;
  order_unit: string;
  use_qty: number;
  use_unit: string;
  safety_qty: number;
  amount: number;
  minimum_amount: number;
  order_total: number;
  status: string;
  basis: string;
}
export interface HubTransfer {
  date: string;
  hub_id: string;
  store_id: string;
  ingredient_id: string;
  ingredient_name: string;
  qty: number;
  use_unit: string;
  response_minutes: number;
  last_use_date: string;
  basis: string;
}
export interface HubShortage {
  date: string;
  store_id: string;
  ingredient_id: string;
  ingredient_name: string;
  qty: number;
  use_unit: string;
  status: string;
  basis: string;
}
export interface HubResponse {
  status: string;
  recommended_hub_count: number | null;
  service_target: number;
  fill_rate: number;
  evaluation_start: string;
  evaluation_end_exclusive: string;
  forecast_basis: string;
  assumptions: string[];
  warnings: string[];
  groups: {
    hub_id: string | null;
    members: string[];
    alpha: number;
    capacity_ok: boolean;
    fleet_ok: boolean;
    peak_liters: Record<string, number>;
    outside_30_minutes: string[];
    basis: string;
  }[];
  alternatives: {
    hub_count: number;
    feasible: boolean;
    economic_cost: number;
    fill_rate: number;
    logistics_cost: number;
    waste_cost: number;
    basis: string;
  }[];
  store_orders: HubOrder[];
  hub_orders: HubOrder[];
  emergency_orders: (HubOrder & { current_day_shortage_resolved: boolean })[];
  transfers: HubTransfer[];
  shortages: HubShortage[];
}
