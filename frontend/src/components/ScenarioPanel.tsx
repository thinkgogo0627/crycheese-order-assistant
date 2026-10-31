import { DATE_RANGE, STORES, useScenario } from '@/lib/scenario'

const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm'

export function ScenarioPanel() {
  const { scenario: s, update, reset } = useScenario()
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">시뮬레이션 조건</h2>
        <button onClick={reset} className="text-xs text-slate-500 hover:text-slate-900">초기화</button>
      </div>
      <label className="block text-xs text-slate-600">판단 기준일 · 오전 09:00
        <input type="date" className={field} min={DATE_RANGE.min} max={DATE_RANGE.max}
          value={s.as_of} onChange={(e) => e.target.value && update({ as_of: e.target.value })} />
      </label>
      <label className="block text-xs text-slate-600">매장 선택
        <select className={field} value={s.store_id} onChange={(e) => update({ store_id: e.target.value })}>
          {STORES.map((st) => <option key={st.id} value={st.id}>{st.id} · {st.name}</option>)}
        </select>
      </label>
      <label className="block text-xs text-slate-600">예측 기간 · {s.horizon_days}일
        <input type="range" min={1} max={14} className="mt-1 w-full"
          value={s.horizon_days} onChange={(e) => update({ horizon_days: Number(e.target.value) })} />
      </label>
      <label className="block text-xs text-slate-600">수요 배율 · ×{s.demand_multiplier.toFixed(1)}
        <input type="range" min={0.5} max={2} step={0.1} className="mt-1 w-full"
          value={s.demand_multiplier} onChange={(e) => update({ demand_multiplier: Number(e.target.value) })} />
      </label>
      <label className="block text-xs text-slate-600">입고 지연 · 가정
        <select className={field} value={s.delay_days} onChange={(e) => update({ delay_days: Number(e.target.value) })}>
          {[0,1,2,3].map((d) => <option key={d} value={d}>{d === 0 ? '없음' : `${d}일`}</option>)}
        </select>
      </label>
      <label className="block text-xs text-slate-600">목표 수요 충족률
        <select className={field} value={s.service_level ?? 'auto'} onChange={(e) => update({ service_level: e.target.value === 'auto' ? null : Number(e.target.value) })}>
          <option value="auto">기본 90%</option>
          {[0.8,0.9,0.95,0.98].map((a) => <option key={a} value={a}>{Math.round(a*100)}%</option>)}
        </select>
      </label>
      <div className="rounded-md border border-emerald-100 bg-emerald-50 p-3 text-xs text-emerald-900">
        <p className="font-semibold">지점 간 이동 · 30분</p>
        <p className="mt-1 text-emerald-800">모든 지점 간 이동시간 30분으로 고정. 09:00 출발 → 09:30 도착, 개점 전 이동 가정.</p>
      </div>
      <label className="block text-xs text-slate-600">운송 1회당 추가 비용 · 원
        <input type="number" min={0} max={100000} step={100} className={field}
          value={s.transfer_cost} onChange={(e) => update({ transfer_cost: Math.max(0, Number(e.target.value)||0) })} />
        <span className="mt-1 block text-[11px] text-slate-400">기본 100원은 임의 가정이며 실제 운임이 아닙니다.</span>
      </label>
      <label className="flex items-start gap-2 text-xs text-slate-600">
        <input type="checkbox" className="mt-0.5" checked={s.can_split_pack} onChange={(e) => update({can_split_pack: e.target.checked})} />
        <span>공동발주 후 포장 소분·매장별 배분 허용 (미확인 가정)</span>
      </label>
    </div>
  )
}
