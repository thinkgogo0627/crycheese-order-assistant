import { DATE_RANGE, useScenario } from "@/lib/scenario";
import { useAuth } from "@/lib/auth";
export function ScenarioPanel() {
  const { draft: s, update, apply, reset, dirty } = useScenario();
  const { account } = useAuth();
  return (
    <form
      className="scenario-panel"
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
      <div className="section-heading">
        <h2>조회 설정</h2>
        <button type="button" className="text-button" onClick={reset}>
          초기화
        </button>
      </div>
      <label>
        판단 기준일
        <input
          type="date"
          min={DATE_RANGE.min}
          max={DATE_RANGE.max}
          required
          value={s.as_of}
          onInput={(e) => update({ as_of: e.currentTarget.value })}
        />
      </label>
      <div className="form-pair">
        <label>
          예측 기간
          <select
            value={s.horizon_days}
            onChange={(e) => update({ horizon_days: +e.target.value })}
          >
            {[1, 3, 7, 14].map((d) => (
              <option key={d} value={d}>
                {d}일
              </option>
            ))}
          </select>
        </label>
        <label>
          입고 지연
          <select
            value={s.delay_days}
            onChange={(e) => update({ delay_days: +e.target.value })}
          >
            {[0, 1, 2, 3].map((d) => (
              <option key={d} value={d}>
                {d}일
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="form-pair">
        <label>
          수요 배율
          <input
            type="number"
            step="0.1"
            min="0.5"
            max="2"
            required
            value={s.demand_multiplier}
            onChange={(e) => update({ demand_multiplier: +e.target.value })}
          />
        </label>
        <label>
          허브 계산 목표 충족률
          <select
            value={s.service_level ?? 0.9}
            onChange={(e) => update({ service_level: +e.target.value })}
          >
            {[0.8, 0.9, 0.95, 0.98].map((v) => (
              <option key={v} value={v}>
                {Math.round(v * 100)}%
              </option>
            ))}
          </select>
        </label>
      </div>
      {account?.role === "hub" && (
        <>
          <label>
            허브 운영 방식
            <select
              value={s.hub_policy}
              onChange={(e) =>
                update({ hub_policy: e.target.value as "auto" | "assigned" })
              }
            >
              <option value="assigned">H01 · S01/S02 고정 운영</option>
              <option value="auto">무허브 포함 대안 탐색</option>
            </select>
          </label>
          <div className="form-pair">
            {(["chilled", "frozen", "ambient"] as const).map((zone, i) => {
              const key = `${zone}_capacity_liters` as const;
              return (
                <label key={zone}>
                  {["냉장", "냉동", "상온"][i]} 여유 공간 · L
                  <input
                    type="number"
                    min="0"
                    max="100000"
                    required
                    value={s[key]}
                    onChange={(e) => update({ [key]: +e.target.value })}
                  />
                </label>
              );
            })}
            <label>
              허브 운영비 · 원/일
              <input
                type="number"
                min="0"
                max="1000000"
                required
                value={s.hub_daily_cost}
                onChange={(e) => update({ hub_daily_cost: +e.target.value })}
              />
            </label>
          </div>
          <label>
            배송비 · 원/회
            <input
              type="number"
              min="0"
              max="100000"
              required
              value={s.transfer_cost}
              onChange={(e) => update({ transfer_cost: +e.target.value })}
            />
          </label>
        </>
      )}
      <button className="button primary" type="submit">
        {dirty ? "변경 조건 적용" : "다시 계산"}
      </button>
    </form>
  );
}
