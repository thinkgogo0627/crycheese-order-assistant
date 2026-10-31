import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export interface TrendRow {
  hour: number; label: string; baseline: number;
  actual: number | null; forecast: number | null;
  lower: number | null; upper: number | null;
  prior_forecast: number | null; absolute_percentage_error: number | null;
}
export interface HourlyTrendData {
  store_id: string; day: string; decision_time: string;
  band_fraction: number; band_note: string; rows: TrendRow[];
}

/** Presentation only. Pass a fresh Python response when completed POS changes. */
export function HourlySalesTrend({ data, height = 340 }: { data: HourlyTrendData; height?: number }) {
  const points = data.rows.map(row => ({ ...row,
    band: row.lower == null || row.upper == null ? null : [row.lower, row.upper],
  }))
  return <section aria-label="시간대별 실판매와 수요 예측">
    <p>{data.store_id} · {data.day} · 판단 시각 {data.decision_time}</p>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={points} margin={{ top: 16, right: 24, bottom: 12, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="label" />
        <YAxis domain={[0, 'auto']} label={{ value: '수량', angle: -90, position: 'insideLeft' }} />
        <Tooltip /><Legend />
        {data.rows.some(row => row.label === data.decision_time) && <ReferenceLine x={data.decision_time} stroke="#f59e0b" strokeDasharray="4 4" label="판단 시각" />}
        <Area type="linear" dataKey="band" name={`예측 ±${Math.round(data.band_fraction * 100)}% 표시 범위`}
          stroke="none" fill="#60a5fa" fillOpacity={0.22} connectNulls={false} isAnimationActive={false} />
        <Line type="linear" dataKey="baseline" name="전일 기준 수요 예측" stroke="#94a3b8" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        <Line type="linear" dataKey="actual" name="확정 실판매" stroke="#059669" strokeWidth={2.5} connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} />
        <Line type="linear" dataKey="forecast" name="갱신된 수요 예측" stroke="#2563eb" strokeWidth={2.5} connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
    <p>음영은 예측값의 ±{Math.round(data.band_fraction * 100)}% 표시 범위이며, 통계적 신뢰구간이나 보장된 오차율이 아닙니다.</p>
    <p>미완료 시간은 실적으로 표시하지 않습니다. 품절 시 실판매는 잠재 수요보다 낮을 수 있습니다.</p>
  </section>
}
