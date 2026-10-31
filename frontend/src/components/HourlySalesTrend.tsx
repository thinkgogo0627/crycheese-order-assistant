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
  return <section className="hourly-trend" aria-label="시간대별 실판매와 수요 예측">
    <p className="muted">{data.store_id} · {data.day} · {data.decision_time} 기준</p>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={points} margin={{ top: 16, right: 24, bottom: 12, left: 8 }}>
        <CartesianGrid stroke="#eee9df" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: '#70695e', fontSize: 13 }} tickLine={false} axisLine={{ stroke: '#ded7ca' }} minTickGap={24} />
        <YAxis domain={[0, 'auto']} tick={{ fill: '#70695e', fontSize: 13 }} tickLine={false} axisLine={false} width={48} label={{ value: '개', position: 'insideTopLeft', fill: '#70695e', fontSize: 13 }} />
        <Tooltip contentStyle={{ border: '1px solid #e8e1d3', borderRadius: 10, fontSize: 14, color: '#302d26' }} labelFormatter={value=>`${value} 시작 시간대`} />
        <Legend wrapperStyle={{ fontSize: 13, paddingTop: 16 }} iconType="plainline" />
        {data.rows.some(row => row.label === data.decision_time) && <ReferenceLine x={data.decision_time} stroke="#8c8170" strokeDasharray="3 5" label={{ value: '기준 시각', fill: '#70695e', fontSize: 12 }} />}
        <Area type="linear" dataKey="band" name={`표시 범위 ±${Math.round(data.band_fraction * 100)}%`}
          stroke="none" fill="#f8b81c" fillOpacity={0.2} connectNulls={false}
          tooltipType="none" legendType="rect" isAnimationActive={false} />
        <Line type="linear" dataKey="baseline" name="기본 예측" stroke="#a69e90" strokeWidth={1.5} strokeDasharray="3 5" dot={false} isAnimationActive={false} />
        <Line type="linear" dataKey="actual" name="판매 실적" stroke="#302d26" strokeWidth={2.5} connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} />
        <Line type="linear" dataKey="forecast" name="판매 반영 예측" stroke="#a96800" strokeWidth={3} strokeDasharray="7 4" connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  </section>
}
