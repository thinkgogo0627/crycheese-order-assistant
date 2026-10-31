import { DATE_RANGE, STORES, useScenario } from '@/lib/scenario'

const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm'

export function ScenarioPanel() {
  const { scenario: s, update, reset } = useScenario()
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">조건</h2>
        <button onClick={reset} className="text-xs text-slate-500 hover:text-slate-900">
          초기화
        </button>
      </div>

      <label className="block text-xs text-slate-600">
        기준일 (그날 아침 발주 판단)
        <input type="date" className={field} min={DATE_RANGE.min} max={DATE_RANGE.max}
          value={s.as_of} onChange={(e) => e.target.value && update({ as_of: e.target.value })} />
      </label>

      <label className="block text-xs text-slate-600">
        매장
        <select className={field} value={s.store_id} onChange={(e) => update({ store_id: e.target.value })}>
          {STORES.map((st) => (
            <option key={st.id} value={st.id}>{st.id} · {st.name}</option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-slate-600">
        예측 기간: {s.horizon_days}일
        <input type="range" min={1} max={14} className="mt-1 w-full"
          value={s.horizon_days} onChange={(e) => update({ horizon_days: Number(e.target.value) })} />
      </label>

      <label className="block text-xs text-slate-600">
        수요 배율: ×{s.demand_multiplier.toFixed(1)}
        <input type="range" min={0.5} max={2} step={0.1} className="mt-1 w-full"
          value={s.demand_multiplier} onChange={(e) => update({ demand_multiplier: Number(e.target.value) })} />
      </label>

      <label className="block text-xs text-slate-600">
        입고 지연 (가상)
        <select className={field} value={s.delay_days} onChange={(e) => update({ delay_days: Number(e.target.value) })}>
          {[0, 1, 2, 3].map((d) => <option key={d} value={d}>{d === 0 ? '없음' : `${d}일`}</option>)}
        </select>
      </label>

      <label className="block text-xs text-slate-600">
        서비스 수준
        <select className={field} value={s.service_level ?? 'auto'}
          onChange={(e) => update({ service_level: e.target.value === 'auto' ? null : Number(e.target.value) })}>
          <option value="auto">품목별 자동</option>
          {[0.8, 0.9, 0.95, 0.98].map((a) => <option key={a} value={a}>{Math.round(a * 100)}%</option>)}
        </select>
      </label>
    </div>
  )
}
