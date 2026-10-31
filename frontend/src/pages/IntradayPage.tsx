import { useState } from 'react'
import { HourlySalesTrend, type HourlyTrendData } from '@/components/HourlySalesTrend'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Clock3, TrendingUp } from 'lucide-react'
import { DATE_RANGE, useScenario } from '@/lib/scenario'
import { apiPost } from '@/lib/api'
import { Card, PageHeader } from '@/components/ui'

interface HourSignal {
  store_id: string; trade_area: string; observed_completed_hours: number;
  observed_sold: number; baseline_same_hours: number; adjustment_factor: number; signal: string
}
interface IntradayResult {
  as_of: string; decision_time: string; data_source: string; observed: HourSignal[];
  hourly_forecast: { hour: string; baseline: number; updated: number }[];
  risks: { store_id: string; ingredient_id: string; ingredient: string; first_at: string;
           shortfall_use_qty: number; unit: string }[];
  transfers: { from_store: string; to_store: string; depart: string; arrive: string;
    minutes: number; trip_cost: number; items: {ingredient: string;qty: number;unit: string}[] }[];
  without_transfer: { unmet_menu_qty: number; fulfilled_menu_qty: number };
  with_transfer: { unmet_menu_qty: number; fulfilled_menu_qty: number };
  predicted_avoided_lost_menu_qty: number;
  snapshot_discrepancies: unknown[];
  assumptions: string[]
}
interface RollingResult {
  trend: HourlyTrendData;
  as_of: string; store_id: string; decision_time: string; data_source: string;
  timeline: {
    hour: string; observed_hours: string[]; observed_sold_cumulative: number;
    baseline_completed_hours: number; adjustment_factor: number;
    baseline_next_hour: number; predicted_next_hour: number;
    top_menus: {menu_id:string;menu:string;baseline:number;predicted:number}[];
  }[]
}
const N = (n: number) => n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
const FIELD = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'

export function IntradayPage({ forecastOnly = false }: { forecastOnly?: boolean } = {}) {
  const { scenario, setAsOf } = useScenario()
  const [time, setTime] = useState('11:00')
  // The calibrated policy stays fixed while operators choose the date and time.
  const horizon = 4
  const strength = null
  const profile = 'protective' as const
  // Explicit date selection: never silently substitute a historical day.
  const day = scenario.as_of
  const replayAvailable = day <= '2026-09-30'
  const input = { as_of: day, decision_time: time, store_id: scenario.store_id,
    horizon_hours: horizon, adjustment_strength: strength, forecast_profile: profile,
    demand_multiplier: scenario.demand_multiplier,
    promotion_multiplier: 1, delay_days: scenario.delay_days, transfer_cost: scenario.transfer_cost }
  const query = useQuery({
    enabled: replayAvailable && !forecastOnly,
    queryKey: ['intraday-replan', input],
    queryFn: () => apiPost<IntradayResult>('/api/intraday_plan', input),
  })
  const rolling = useQuery({
    enabled: replayAvailable,
    queryKey: ['intraday-rolling', input],
    queryFn: () => apiPost<RollingResult>('/api/hourly_forecast', input),
  })
  const p = forecastOnly ? undefined : query.data
  const selected = p?.observed.find(x=>x.store_id===scenario.store_id)
  return <>
    <PageHeader title={forecastOnly ? "시간별 수요" : "시간별 부족 확인"} description="기준 시각까지의 판매량과 이후 예상 수요를 확인합니다." />
    <Card>
      <div className="time-selector-row">
        <label>조회 날짜
          <input type="date" min={DATE_RANGE.min} max={DATE_RANGE.max} required
            value={day} onChange={e=>{
              if(e.currentTarget.value && e.currentTarget.validity.valid) setAsOf(e.currentTarget.value)
            }} />
        </label>
        <label>기준 시각
          <select className={`${FIELD} mt-2`} value={time} onChange={e=>setTime(e.target.value)}>
            {Array.from({length:11},(_,i)=>i+10).map(h=><option key={h} value={`${String(h).padStart(2,'0')}:00`}>{h}:00</option>)}
          </select>
        </label>
        <p className="muted">선택한 시각 이전에 완료된 판매량을 반영합니다.</p>
      </div>
    </Card>
    <div className="mt-4"><Card title="판매 실적과 예상 수요">
      {rolling.isFetching && replayAvailable && <p role="status">예측 갱신 중…</p>}
      {rolling.isError && <p role="alert">그래프 계산 오류: {rolling.error.message}</p>}
      {replayAvailable && rolling.data && <HourlySalesTrend data={rolling.data.trend} />}
      {!replayAvailable && <p role="status">선택한 날짜의 판매 기록이 없습니다.</p>}
    </Card></div>
    <details className="detail-section"><summary>시간별 판매·예측 수치</summary><Card>
      {replayAvailable && rolling.isPending && <p className="text-xs text-slate-500">시간별 누적 예측 계산 중…</p>}
      {rolling.isError && <p className="text-xs text-red-700">누적 예측 오류: {rolling.error.message}</p>}
      {replayAvailable && rolling.data && <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead><tr className="border-b text-xs text-slate-500"><th className="py-2">예측 시간</th><th>반영한 실판매 시간</th><th>누적 판매</th><th>기본 예측</th><th>수정 예측</th></tr></thead>
        <tbody>{rolling.data.timeline.map(x=><tr key={x.hour} className="border-b border-slate-100">
          <td className="py-2 font-semibold">{x.hour}</td>
          <td>{x.observed_hours.length ? `${x.observed_hours[0]}~${x.hour} 이전` : '없음'}</td>
          <td>{N(x.observed_sold_cumulative)}개</td>
          <td>{N(x.baseline_next_hour)}개</td>
          <td className="font-semibold text-[#8a5900]">{N(x.predicted_next_hour)}개</td>
        </tr>)}</tbody>
      </table></div>}
      {replayAvailable && rolling.data?.timeline.length ? <p className="mt-3 text-xs text-slate-500">마지막 예측 주요 메뉴: {rolling.data.timeline[rolling.data.timeline.length-1].top_menus.slice(0,3).map(m=>`${m.menu} ${N(m.predicted)}개`).join(' · ')}</p> : null}
    </Card></details>
    {!forecastOnly && replayAvailable && query.isPending && <div className="mt-4"><Card>시간별 판매 기록을 재생하고 있습니다…</Card></div>}
    {!forecastOnly && query.isError && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">계산 오류: {query.error.message}</div>}
    {p && <>
      <div className="my-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['완료된 관측 시간',`${selected?.observed_completed_hours ?? 0}시간`,<Clock3 key="clock" size={18}/>],
          ['확정 판매 실적',`${N(selected?.observed_sold ?? 0)}개`,<TrendingUp key="trend" size={18}/>],
          ['이동 전 예측 미판매',`${N(p.without_transfer.unmet_menu_qty)}개`,<ArrowLeftRight key="transfer" size={18}/>],
          ['30분 이동으로 구제 예상',`${N(p.predicted_avoided_lost_menu_qty)}개`,<TrendingUp key="trend" size={18}/>],
        ].map(([name,value,icon])=><div key={String(name)} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500"><span>{name}</span>{icon}</div>
          <div className="mt-2 text-xl font-bold">{value}</div>
        </div>)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`${scenario.store_id} · 다음 시간대 수요`}>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead><tr className="border-b text-xs text-slate-500"><th className="py-2">시간</th><th>실적 반영 전</th><th>반영 후</th></tr></thead>
            <tbody>{p.hourly_forecast.map(x=><tr key={x.hour} className="border-b border-slate-100"><td className="py-2">{x.hour}</td><td>{N(x.baseline)}개</td><td className="font-semibold">{N(x.updated)}개</td></tr>)}</tbody>
          </table></div>
        </Card>
        <Card title="매장별 관측 판매와 보정계수">
          {p.observed.map(x=><div key={x.store_id} className="border-b border-slate-100 py-2 text-sm">
            <b>{x.store_id}</b> <span className="text-xs text-slate-500">{x.trade_area}</span>
            <p className="mt-1 text-xs">실판매 {N(x.observed_sold)}개 / 기본예측 {N(x.baseline_same_hours)}개 · 보정 {N(x.adjustment_factor)}배</p>
            <p className="mt-1 text-xs text-slate-500">{x.signal}</p>
          </div>)}
        </Card>
        <Card title="30분 후 도착하는 이동 초안">
          {p.transfers.length===0 && <p className="text-sm text-slate-500">이동 예정 물량이 없습니다.</p>}
          {p.transfers.map((t,i)=><div key={i} className="mb-3 rounded-lg border border-emerald-100 bg-emerald-50 p-3 text-sm">
            <b>{t.from_store} → {t.to_store}</b>
            <p className="mt-1 text-xs">{t.depart} 출발 → {t.arrive} 도착 · 이동 비용 {t.trip_cost}원</p>
            <p className="mt-2 text-xs">{t.items.map(x=>`${x.ingredient} ${N(x.qty)}${x.unit}`).join(' / ')}</p>
          </div>)}
        </Card>
        <Card title="예상 품절 위험">
          {p.risks.length===0 && <p className="text-sm text-slate-500">현재 예측 구간 내 위험 없음</p>}
          {p.risks.slice(0,20).map((r,i)=><p key={i} className="border-b border-slate-100 py-2 text-xs">
            <b>{r.store_id} · {r.ingredient}</b> · {r.first_at} 첫 부족 예상 · {N(r.shortfall_use_qty)}{r.unit}
          </p>)}
        </Card>
      </div>
      {p.snapshot_discrepancies.length>0 && <p className="error-text">실제 재고를 확인해 주세요.</p>}
    </>}
  </>
}
