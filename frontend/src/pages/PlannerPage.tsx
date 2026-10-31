import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, Package, ShoppingCart, TrendingUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { apiPost } from '@/lib/api'
import { useScenario } from '@/lib/scenario'
import { Card, PageHeader } from '@/components/ui'
import type { PlanResponse } from '@/types/api'

const KRW = (v: number) => Math.round(v).toLocaleString('ko-KR') + '원'
const NUM = (v: number) => v.toLocaleString('ko-KR', {maximumFractionDigits: 1})
const MODES: Record<string,string> = {independent: 'M0 · 매장별 독립 발주', pooled: 'M1 · 공동발주',shared: 'M2 · 공동발주 + 재고 이동'}

export function usePlan() {
  const { scenario } = useScenario()
  return useQuery({
    queryKey: ['plan', scenario],
    queryFn: () => apiPost<PlanResponse>('/api/plan', scenario),
    placeholderData: (previous) => previous,
  })
}

function DashboardBoundary({ children }: { children: (p:PlanResponse) => ReactNode }) {
  const q = usePlan()
  if (q.isPending) return <Card title="계산 중">원본 CSV 기반으로 계산 중입니다…</Card>
  if (q.isError) return <div className="rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-700">계산 실패: {q.error.message}. 백엔드 실행 여부와 비공개 CSV 경로를 확인하세요.</div>
  if (!q.data) return null
  return <div className={q.isFetching ? 'opacity-70' : ''}>{children(q.data)}{q.isFetching && <p className="mt-3 text-xs text-amber-700">조건 변경을 계산하고 있습니다…</p>}</div>
}

function Summary({p}:{p:PlanResponse}) {
  const selected = p.comparison.find(x=>x.mode===p.recommended_mode)!
  return <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
    {[
      ['추천 방식',MODES[p.recommended_mode],<Package size={18} />],
      ['수요 충족률', `${selected.fill_rate.toFixed(1)}%`, <TrendingUp size={18}/>],
      ['기간 예상 구매액',KRW(selected.purchase_cost),<ShoppingCart size={18}/>],
      ['운송 횟수', `${selected.trip_count}회 · 30분/회`, <ArrowLeftRight size={18}/>],
    ].map(([name,val,icon])=><div key={String(name)} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between text-xs text-slate-500"><span>{name}</span>{icon}</div>
      <p className="mt-2 text-lg font-bold text-slate-900">{val}</p>
    </div>)}
  </div>
}

export function OrdersPage() {
  return <>
    <PageHeader title="발주 추천" description="미래 수요·기존 재고·미입고 발주를 반영하고, 최소발주금액과 포장단위를 적용합니다." />
    <DashboardBoundary>{(p)=><>
      <Summary p={p}/>
      <Card title="현재 추천과 한계">
        <p className="text-sm leading-6"><b>{MODES[p.recommended_mode]}</b>을 현재 조건의 추천안으로 표시합니다. 서비스 수준 {p.service_target}%를 충족하는 정책 중 예상 기여도가 높은 정책을 선택하며, 어떤 정책도 기준을 달성하지 못하면 충족률이 높은 정책을 표시합니다.</p>
        <p className="mt-2 text-xs text-amber-800">실제 재고가 아니라 과거 스냅샷 기반 시뮬레이션이며, 시스템에서 주문을 실행하지 않습니다.</p>
      </Card>
      <div className="mt-4"><Card title={`발주 초안 · 판단일 ${p.as_of}`}>
        {p.all_orders.length===0?<p className="text-sm text-slate-500">해당 일자의 발주 초안 없음. 발주 요일·최소금액 미달·재고 충분 여부를 확인하세요.</p>:<div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="border-b text-xs text-slate-500"><th className="py-2">공급사</th><th>품목</th><th>배분 대상</th><th>발주량</th><th>입고일</th><th className="text-right">금액</th></tr></thead>
          <tbody>{p.all_orders.map((x,j)=><tr className="border-b border-slate-100" key={j}>
            <td className="py-2">{x.supplier}</td><td>{x.ingredient}</td><td>{x.store_id==='ALL'?'3개 매장 통합':x.store_id}<div className="text-[11px] text-slate-400">{Object.entries(x.allocated).map(([k,v])=>`${k} ${NUM(v)}`).join(' / ')}</div></td>
            <td>{x.order_qty}{x.order_unit}</td><td>{x.arrival_date}</td><td className="text-right">{KRW(x.amount)}</td>
          </tr>)}</tbody>
        </table></div>}
      </Card></div>
      {p.blocked.length>0 && <div className="mt-4"><Card title="공급사 제약으로 보류된 주문">
        <div className="space-y-2">{p.blocked.slice(0,8).map((x,i)=><p className="text-xs text-amber-900" key={i}><AlertTriangle className="mr-1 inline" size={13}/>{x.date} · {x.supplier} · {x.store}: {KRW(x.amount)} / 최소 {KRW(x.minimum)}</p>)}</div>
      </Card></div>}
    </>}</DashboardBoundary>
  </>
}

export function InventoryPage() {
  return <>
    <PageHeader title="재고·소비기한 알림" description="lot별 만료일, 매장별 식자재 재고, 사용 가능한 잉여를 비교합니다." />
    <DashboardBoundary>{(p)=><>
      <Card title={`${p.store_id} · 현재 예측 위험`}>
        {p.alerts.length===0?<p className="text-sm text-slate-500">선택한 기준일의 경보 없음</p>:<div className="grid gap-2 md:grid-cols-2">{p.alerts.map((a,j)=><div key={j} className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <div className="text-xs font-semibold text-amber-900">{a.type==='shortage'?'예상 부족':a.type==='expired'?'기한 경과':a.type==='overstock'?'과잉재고 추정':'소비기한 임박'} · {a.name}</div>
          <p className="mt-1 text-sm">{NUM(a.qty)}{a.unit} · {a.date}</p>
        </div>)}</div>}
      </Card>
      <div className="mt-4"><Card title="식자재별 현재 재고와 오늘 예상 소요량">
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b text-xs text-slate-500"><th className="py-2">식자재</th><th>보유 수량</th><th>예상 소요</th><th>가장 가까운 소비기한</th></tr></thead>
          <tbody>{p.ingredients.filter(i=>i.predicted_today>0).sort((a,b)=>b.predicted_today/(b.current_stock+1)-a.predicted_today/(a.current_stock+1)).map((i)=><tr key={i.ingredient_id} className="border-b border-slate-100"><td className="py-2">{i.ingredient}</td><td>{NUM(i.current_stock)}{i.unit}</td><td>{NUM(i.predicted_today)}{i.unit}</td><td>{i.expiry_nearest ?? '재고 없음'}</td></tr>)}</tbody>
        </table></div>
      </Card></div>
    </>}</DashboardBoundary>
  </>
}

export function ForecastPage() {
  return <>
    <PageHeader title="판매 수요 예측" description="최근 7일 평균 50% + 최근 관측 동일 요일 평균 50% 기반 수요 예측과 BOM 식자재 변환입니다." />
    <DashboardBoundary>{(p)=><div className="grid gap-4 lg:grid-cols-2">
      <Card title={`${p.store_id} · 예측 메뉴 수요 (첫날)`}>
        <div className="space-y-2">{[...p.forecast].sort((a,b)=>b.qty-a.qty).map((m)=><div key={m.menu_id} className="flex items-center justify-between border-b border-slate-100 pb-2 text-sm"><span>{m.menu}</span><b>{NUM(m.qty)}개</b></div>)}</div>
      </Card>
      <Card title="BOM 변환 식자재 예상 소요 (첫날)">
        <div className="space-y-2">{p.ingredients.filter(i=>i.predicted_today>0).sort((a,b)=>b.predicted_today-a.predicted_today).map((i)=><div key={i.ingredient_id} className="flex items-center justify-between border-b border-slate-100 pb-2 text-sm"><span>{i.ingredient}</span><b>{NUM(i.predicted_today)}{i.unit}</b></div>)}</div>
      </Card>
    </div>}</DashboardBoundary>
  </>
}

export function ComparePage() {
  return <>
    <PageHeader title="대안별 비용·품절·폐기 비교" description="동일한 미래 예측수요를 사용해 독립발주, 공동발주, 공동발주+재고 이동을 비교합니다." />
    <DashboardBoundary>{(p)=><>
      <Summary p={p}/>
      <Card title="기간 전체 · 3개 매장 비교">
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b text-xs text-slate-500"><th className="py-2">지표</th>{p.comparison.map(r=><th className="p-2 text-right" key={r.mode}>{MODES[r.mode]}</th>)}</tr></thead>
        <tbody>{([
          ['수요 충족률', r=>r.fill_rate.toFixed(2)+'%'],
          ['예상 매출',r=>KRW(r.expected_revenue)],
          ['발주 구매액',r=>KRW(r.purchase_cost)],
          ['이동 비용',r=>KRW(r.transport_cost)],
          ['예상 폐기 원가',r=>KRW(r.waste_cost)],
          ['미판매 예상 메뉴 수',r=>NUM(r.lost_qty)+'개'],
          ['신규 발주 포장',r=>NUM(r.ordered_packs)+'개'],
          ['운송 횟수',r=>r.trip_count+'회'],
          ['기말 유효재고 가치',r=>KRW(r.closing_value)],
          ['기여도 근사 (참고)',r=>KRW(r.contribution_after_waste_and_transport)],
        ] as [string, (r: PlanResponse['comparison'][number]) => string][]).map(([title,fn],index)=><tr key={index} className="border-b border-slate-100"><td className="py-3 font-medium">{String(title)}</td>{p.comparison.map(r=><td key={r.mode} className="p-2 text-right">{(fn as (x:typeof r)=>string)(r)}</td>)}</tr>)}</tbody>
        </table></div>
        <p className="mt-3 text-xs text-slate-500">기여도 근사 = 예상 매출 − 사용 식자재 원가 − 만료 폐기원가 − 이동비. 식자재 구매액을 다시 차감하지 않으며, 다른 인건비·점포 고정비는 미반영. 시뮬레이션 수치로 실제 절감액이 아닙니다.</p>
      </Card>
      <div className="mt-4"><Card title="공동재고 이동 가능안 (M2 시뮬레이션 · 오전 9시 출발)">
        {p.shared_alternative_transfers.length===0?<p className="text-sm text-slate-500">현재 선택한 날짜 오전에는 제안 가능한 이동 없음. 향후 일정에서 이동이 발생할 수 있습니다.</p>:<div className="space-y-4">{p.shared_alternative_transfers.map((t,j)=><div key={j} className="rounded-lg border border-slate-200 p-3">
          <div className="flex items-center justify-between gap-2"><b className="text-sm">{t.from_store} → {t.to_store}</b><span className="text-xs text-slate-600">{t.depart} 출발 · {t.arrive} 도착 · {KRW(t.trip_cost)}/회</span></div>
          <p className="mt-2 text-xs text-slate-700">{t.items.map(x=>`${x.ingredient} ${NUM(x.qty)}${x.unit}`).join(' · ')}</p>
        </div>)}</div>}
      </Card></div>
      <div className="mt-4"><Card title="모델 및 운영 가정">
        <ul className="list-disc space-y-2 pl-4 text-xs leading-5 text-slate-600">{p.assumptions.map((a,i)=><li key={i}>{a}</li>)}</ul>
        {p.data_issues.length>0 && <p className="mt-3 text-xs text-amber-800">자료 검증 경고: {p.data_issues.join(', ')}</p>}
      </Card></div>
    </>}</DashboardBoundary>
  </>
}
