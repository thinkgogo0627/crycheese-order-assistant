import { useState } from 'react'
import { Card } from '@/components/ui'
import type { PlanResponse } from '@/types/api'
import { draftRows } from '@/lib/orderDraft'

const money = (n: number) => Math.round(n).toLocaleString('ko-KR') + '원'
const quantity = (n: number) => n.toLocaleString('ko-KR', { maximumFractionDigits: 1 })

export function OrderDraft({ plan }: { plan: PlanResponse }) {
  const [allStores, setAllStores] = useState(false)
  const rows = draftRows(plan, allStores)
  const scope = allStores ? '전체 매장' : plan.store_id
  const pooled = rows.some(row => row.store_id === 'ALL')
  const suppliers = [...new Set(rows.map(row => row.supplier_id))]
  const blocked = plan.blocked.filter(row => row.date === plan.as_of && row.action !== '채움' &&
    (allStores || row.store === plan.store_id || row.store === 'ALL'))

  return <div className="space-y-4">
    <Card title={`${scope} · ${plan.as_of} 발주 초안`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-lg font-bold text-slate-900">
            {rows.length ? `발주할 품목 ${new Set(rows.map(row => row.ingredient_id)).size}종` : '발주 추천 품목 없음'}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            공급사 {suppliers.length}곳 · {pooled && !allStores ? '선택 매장 포함 주문액' : '발주 초안 금액'}{' '}
            <strong className="text-slate-900">{money(rows.reduce((sum, row) => sum + row.amount, 0))}</strong>
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm">
          <input type="checkbox" checked={allStores} onChange={event => setAllStores(event.target.checked)} />
          전체 매장 보기
        </label>
      </div>
      <p className="text-xs text-slate-500">선택한 기준일에 넣을 주문 초안입니다. 실제 주문은 실행되지 않습니다. 금액은 가상 가격입니다.</p>
      {pooled && <p className="mt-2 text-xs text-amber-800">
        통합발주의 발주량·금액은 공동 주문 전체 기준입니다. 선택 매장의 배분 수량과 구분해서 확인하세요.
      </p>}
    </Card>

    {rows.length === 0 && <Card>
      <p className="text-sm text-slate-600">{scope}의 {plan.as_of} 발주 초안이 없습니다. 발주 가능 요일, 재고와 예정 입고, 최소금액으로 보류된 주문을 확인하세요.</p>
    </Card>}

    {suppliers.map(supplier => {
      const lines = rows.filter(row => row.supplier_id === supplier)
      return <Card key={supplier} title={`${lines[0].supplier} · ${money(lines.reduce((sum, row) => sum + row.amount, 0))}`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" aria-label={`${lines[0].supplier} 발주 품목`}>
            <thead><tr className="border-b text-xs text-slate-500">
              <th scope="col" className="pb-2">발주할 품목</th><th scope="col">발주 수량</th>
              <th scope="col">입고 예정일</th><th scope="col">배분 대상</th><th scope="col" className="text-right">주문 금액</th>
            </tr></thead>
            <tbody>{lines.map((row, index) => <tr key={`${row.store_id}:${row.ingredient_id}:${index}`} className="border-b border-slate-100">
              <td className="py-3 pr-4">
                <span className="font-semibold text-slate-900">{row.ingredient}</span>
                {row.reason && <details className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                  <summary className="cursor-pointer">추천 근거</summary>{row.reason}
                </details>}
              </td>
              <td className="whitespace-nowrap pr-4 font-bold">{quantity(row.order_qty)} {row.order_unit}
                {row.store_id === 'ALL' && <span className="block text-xs font-normal text-slate-500">통합 주문량</span>}
              </td>
              <td className="whitespace-nowrap pr-4">{row.arrival_date}</td>
              <td className="pr-4 text-xs">
                {Object.entries(row.allocated).filter(([store, qty]) => qty > 0 && (allStores || store === plan.store_id))
                  .map(([store, qty]) => <div key={store}>{store} · {quantity(qty)} {row.unit ?? '사용 단위'}</div>)}
              </td>
              <td className="whitespace-nowrap text-right">{money(row.amount)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </Card>
    })}

    {blocked.length > 0 && <Card title={`${scope} · 공급사 조건으로 보류된 주문`}>
      <div className="space-y-2">{blocked.map((row, index) => <p key={index} className="text-xs leading-5 text-amber-900">
        {row.supplier} · {row.store} · {money(row.amount)} / 최소 {money(row.minimum)}<br />{row.reason}
      </p>)}</div>
    </Card>}
  </div>
}
