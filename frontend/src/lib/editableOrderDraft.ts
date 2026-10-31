import type { HubOrder } from '@/types/api'

export function readOrderQuantity(value: string): number | null {
  if (!/^\d+$/.test(value)) return null
  const quantity = Number(value)
  return Number.isSafeInteger(quantity) ? quantity : null
}

// The API exposes rounded line amounts, so edited amounts remain estimates.
export function applyOrderQuantity(row: HubOrder, value: string): HubOrder | null {
  const quantity = readOrderQuantity(value)
  if (quantity === null || row.order_qty <= 0) return null
  const ratio = quantity / row.order_qty
  const amount = Math.round(row.amount * ratio)
  const useQty = row.use_qty * ratio
  if (!Number.isSafeInteger(amount) || !Number.isFinite(useQty)) return null
  return { ...row, order_qty: quantity, amount, use_qty: useQty }
}

export function orderGroupKey(row: HubOrder): string {
  return JSON.stringify([row.store_id, row.supplier_id, row.order_date])
}

export function orderMinimumChecks(original: HubOrder[], edited: (HubOrder | null)[]) {
  const groups = new Map<string, {
    key: string; store: string; supplier: string; date: string;
    amount: number; minimum: number; valid: boolean; active: boolean;
  }>()
  original.forEach((row, index) => {
    const key = orderGroupKey(row)
    const group = groups.get(key) ?? { key, store: row.store_id,
      supplier: row.supplier_id, date: row.order_date,
      amount: 0, minimum: 0, valid: true, active: false }
    group.minimum = Math.max(group.minimum, row.minimum_amount ?? 0)
    const value = edited[index]
    if (value === null || value === undefined) group.valid = false
    else if (value.order_qty > 0) {
      group.amount += value.amount
      group.active = true
    }
    groups.set(key, group)
  })
  return [...groups.values()].map(group => ({ ...group,
    below: group.valid && group.active && group.amount < group.minimum,
  }))
}

export function orderDraftCsv(rows: HubOrder[]): string {
  const lines: (string | number)[][] = [
    ['매장', '식자재', '발주일', '입고일', '포장 수량', '단위', '금액', '상태'],
    ...rows.filter(row => row.order_qty > 0).map(row => [
      row.store_id, row.ingredient_name, row.order_date, row.arrival_date,
      row.order_qty, row.order_unit, row.amount, row.status,
    ]),
  ]
  return '\uFEFF' + lines.map(line => line.map(value =>
    `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\r\n')
}
