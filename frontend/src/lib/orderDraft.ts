import type { PlanResponse } from '@/types/api'

export function draftRows(plan: PlanResponse, allStores = false) {
  return (allStores ? plan.all_orders : plan.orders)
    .filter(row => row.order_date === plan.as_of && row.order_qty > 0 && (
      allStores || row.store_id === plan.store_id ||
      (row.store_id === 'ALL' && (row.allocated[plan.store_id] ?? 0) > 0)
    ))
    .sort((a, b) => a.supplier_id.localeCompare(b.supplier_id) ||
      a.arrival_date.localeCompare(b.arrival_date) || a.ingredient.localeCompare(b.ingredient, 'ko'))
}
