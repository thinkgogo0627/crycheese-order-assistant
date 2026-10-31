import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Clock3, TrendingUp } from 'lucide-react'
import { useScenario } from '@/lib/scenario'
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
  const { scenario, update } = useScenario()
  const [time, setTime] = useState('11:00')
  const [horizon, setHorizon] = useState(4)
  const [strength, setStrength] = useState<number | null>(null)
  const [profile, setProfile] = useState<'protective'|'balanced'|'original'>('protective')
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
    <PageHeader title={forecastOnly ? "실판매 기반 시간별 수요" : "실판매 기반 시간별 재계획"} description={forecastOnly ? "선택 매장의 완료된 시간 판매량으로 다음 시간대 수요를 보정합니다." : "완료된 시간의 실판매량으로 다음 시간대 수요를 보정하고, 30분 이동 후 품절손실 감소를 검증합니다."} />
    {!forecastOnly && <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
      <b>시뮬레이션 가정:</b> 이동 30분, 운송비는 왼쪽 입력값을 사용합니다. 소분 가능·동시 운송 가능을 가정한 검토용 초안입니다. 단, 실제 POS 연동·직원 이동 가능 여부·실측 현재고는 미검증입니다.
      <p className="mt-2 text-xs">S01·S03는 10시에, S02는 11시에 개점하므로 <b>10시 정각에는 전 시간대 실판매 관측값이 없습니다.</b> 11시에는 S01·S03의 10~11시 실적을 사용합니다.</p>
    </div>}
    {forecastOnly && <div className="notice"><p>우리 매장의 완료된 POS 시간만 반영하는 과거 데이터 재생입니다. 실시간 POS에 연결된 화면은 아니며, 발주·허브 공급은 각 업무 화면에서 확인합니다.</p></div>}
    {!replayAvailable && <Card title="이 날짜의 당일 POS 기록이 없습니다">
      <p className="text-sm">기준일을 자동 변경하지 않습니다. 과거 재생 날짜를 직접 선택하거나 API에 전체 완료시간 POS 스냅샷을 제공하세요.</p>
      {forecastOnly ? <p className="hint">상단 분석 조건에서 2026년 9월 30일 이전을 선택하고 조건을 적용하세요.</p> : <button className="mt-2 rounded border px-3 py-2" onClick={()=>update({as_of:'2026-09-30'})}>9월 30일로 변경하여 재생</button>}
    </Card>}
    {!forecastOnly && <p className="my-3 text-xs text-slate-600">이 화면은 시간별 잠재 수요와 이동 초안의 실험 기능입니다. 기존 일별 발주 모델은 유지됩니다. 일별 예측기간·서비스 수준·공동발주 소분 설정은 이 화면에 적용되지 않습니다. 이동의 경제성 최적화는 수행하지 않습니다.</p>}
    <Card title="시간별 재계획 조건">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-slate-600">관찰 시각
          <select className={`${FIELD} mt-2`} value={time} onChange={e=>setTime(e.target.value)}>
            {Array.from({length:11},(_,i)=>i+10).map(h=><option key={h} value={`${String(h).padStart(2,'0')}:00`}>{h}:00</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">미래 예측 구간
          <select className={`${FIELD} mt-2`} value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>
            {[2,4,6,8].map(h=><option key={h} value={h}>{h}시간</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">예측 정책
          <select className={`${FIELD} mt-2`} value={profile} onChange={e=>setProfile(e.target.value as typeof profile)}>
            <option value="protective">품절 보호 · 7월 검증</option>
            <option value="balanced">WAPE 최소 · 7월 검증</option>
            <option value="original">기존 초기 설정</option>
          </select>
        </label>
        <label className="text-xs text-slate-600">보정 강도 직접 변경 (선택 사항)
          <select className={`${FIELD} mt-2`} value={strength === null ? 'auto' : String(strength)} onChange={e=>setStrength(e.target.value==='auto'?null:Number(e.target.value))}>
            <option value="auto">정책 선택값 자동 적용</option>
            {[0,0.2,0.4,0.6,0.8].map(x=><option key={x} value={x}>{x.toFixed(1)}</option>)}
          </select>
        </label>
      </div>
      <p className="mt-3 text-xs text-slate-500">품절 보호 정책은 실제 식자재 비용으로 추정된 손실비율이 아니라 과소예측에 1.5배를 주는 민감도 실험입니다. 분석일: {day} · {scenario.store_id}. 이전 기간 재생 기능이며, 현재 POS를 직접 읽는 기능이 아닙니다. 기준일은 상단 분석 조건에서 변경하고, 매장은 로그인 계정 기준으로 고정됩니다.</p>
    </Card>
    <div className="mt-4"><Card title="당일 판매량 누적 → 다음 1시간 예측 (매시간 업데이트)">
      <p className="mb-3 text-xs text-slate-500">10:00은 10:00~10:59 판매 구간입니다. 각 예측에는 직전까지 <b>완료된 시간의 POS 판매량만</b> 누적됩니다.</p>
      {replayAvailable && rolling.isPending && <p className="text-xs text-slate-500">시간별 누적 예측 계산 중…</p>}
      {rolling.isError && <p className="text-xs text-red-700">누적 예측 오류: {rolling.error.message}</p>}
      {rolling.data && <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead><tr className="border-b text-xs text-slate-500"><th className="py-2">예측 시간</th><th>반영한 실판매 시간</th><th>누적 판매</th><th>기본 예측</th><th>수정 예측</th></tr></thead>
        <tbody>{rolling.data.timeline.map(x=><tr key={x.hour} className="border-b border-slate-100">
          <td className="py-2 font-semibold">{x.hour}</td>
          <td>{x.observed_hours.length ? `${x.observed_hours[0]}~${x.hour} 이전` : '없음'}</td>
          <td>{N(x.observed_sold_cumulative)}개</td>
          <td>{N(x.baseline_next_hour)}개</td>
          <td className="font-semibold text-emerald-700">{N(x.predicted_next_hour)}개</td>
        </tr>)}</tbody>
      </table></div>}
      {rolling.data?.timeline.length ? <p className="mt-3 text-xs text-slate-500">마지막 예측 주요 메뉴: {rolling.data.timeline[rolling.data.timeline.length-1].top_menus.slice(0,3).map(m=>`${m.menu} ${N(m.predicted)}개`).join(' · ')}</p> : null}
    </Card></div>
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
          <p className="mt-3 text-xs text-slate-500">관측 없음, 보정 강도 0 또는 관측과 기본예측이 일치하면 수정값이 기본값과 같을 수 있습니다.</p>
        </Card>
        <Card title="매장별 관측 판매와 보정계수">
          {p.observed.map(x=><div key={x.store_id} className="border-b border-slate-100 py-2 text-sm">
            <b>{x.store_id}</b> <span className="text-xs text-slate-500">{x.trade_area}</span>
            <p className="mt-1 text-xs">실판매 {N(x.observed_sold)}개 / 기본예측 {N(x.baseline_same_hours)}개 · 보정 {N(x.adjustment_factor)}배</p>
            <p className="mt-1 text-xs text-slate-500">{x.signal}</p>
          </div>)}
        </Card>
        <Card title="30분 후 도착하는 이동 초안">
          {p.transfers.length===0 && <p className="text-sm text-slate-500">이번 관측 시점에서는 이동을 권고하지 않습니다. 실적 보정·재고·도착시점을 고려한 결과입니다.</p>}
          {p.transfers.map((t,i)=><div key={i} className="mb-3 rounded-lg border border-emerald-100 bg-emerald-50 p-3 text-sm">
            <b>{t.from_store} → {t.to_store}</b>
            <p className="mt-1 text-xs">{t.depart} 출발 → {t.arrive} 도착 · 이동 비용 {t.trip_cost}원</p>
            <p className="mt-2 text-xs">{t.items.map(x=>`${x.ingredient} ${N(x.qty)}${x.unit}`).join(' / ')}</p>
          </div>)}
          <p className="text-xs text-slate-500">이동 권고는 실제 지시/예약이 아닙니다. 도착 전 부족은 구제하지 못하는 것으로 계산합니다.</p>
        </Card>
        <Card title="예상 품절 위험">
          {p.risks.length===0 && <p className="text-sm text-slate-500">현재 예측 구간 내 위험 없음</p>}
          {p.risks.slice(0,20).map((r,i)=><p key={i} className="border-b border-slate-100 py-2 text-xs">
            <b>{r.store_id} · {r.ingredient}</b> · {r.first_at} 첫 부족 예상 · {N(r.shortfall_use_qty)}{r.unit}
          </p>)}
        </Card>
      </div>
      <div className="mt-4"><Card title="예측 근거와 운영상 한계">
        <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-slate-600">{p.assumptions.map((a,i)=><li key={i}>{a}</li>)}</ul>
        {p.snapshot_discrepancies.length>0 && <p className="mt-2 text-xs text-red-700">관측 판매량과 추정 재고 소진이 일치하지 않는 품목이 있습니다. 매장 실측 재고 확인이 필요합니다.</p>}
      </Card></div>
    </>}
  </>
}
