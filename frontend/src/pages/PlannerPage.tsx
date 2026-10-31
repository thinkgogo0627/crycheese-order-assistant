import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { apiPost } from "@/lib/api";
import { useScenario } from "@/lib/scenario";
import { Card, PageHeader } from "@/components/ui";
import type { PlanResponse } from "@/types/api";

const NUM = (v: number) =>
  v.toLocaleString("ko-KR", { maximumFractionDigits: 1 });

// eslint-disable-next-line react-refresh/only-export-components
export function usePlan() {
  const { scenario } = useScenario();
  return useQuery({
    queryKey: ["plan", scenario],
    queryFn: () => apiPost<PlanResponse>("/api/plan", scenario),
  });
}

function DashboardBoundary({
  children,
}: {
  children: (p: PlanResponse) => ReactNode;
}) {
  const q = usePlan();
  if (q.isPending)
    return <Card title="계산 중">원본 CSV 기반으로 계산 중입니다…</Card>;
  if (q.isError)
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        계산 실패: {q.error.message}. 데이터 연결을 확인한 뒤 다시 시도해
        주세요.
      </div>
    );
  if (!q.data) return null;
  return (
    <div className={q.isFetching ? "opacity-70" : ""}>
      {children(q.data)}
      {q.isFetching && (
        <p className="mt-3 text-xs text-amber-700">
          조건 변경을 계산하고 있습니다…
        </p>
      )}
    </div>
  );
}

export function InventoryPage() {
  return (
    <>
      <PageHeader
        title="재고·소비기한 알림"
        description="lot별 만료일, 매장별 식자재 재고, 사용 가능한 잉여를 비교합니다."
      />
      <DashboardBoundary>
        {(p) => (
          <>
            <Card title={`${p.store_id} · 현재 예측 위험`}>
              {p.alerts.length === 0 ? (
                <p className="text-sm text-slate-500">
                  선택한 기준일의 경보 없음
                </p>
              ) : (
                <div className="grid gap-2 md:grid-cols-2">
                  {p.alerts.map((a, j) => (
                    <div
                      key={j}
                      className="rounded-lg border border-amber-200 bg-amber-50 p-3"
                    >
                      <div className="text-xs font-semibold text-amber-900">
                        {a.type === "shortage"
                          ? "예상 부족"
                          : a.type === "expired"
                            ? "기한 경과"
                            : a.type === "overstock"
                              ? "과잉재고 추정"
                              : a.type === "deadstock"
                                ? "메뉴 운영 종료 잔여"
                                : "소비기한 임박"}{" "}
                        · {a.name}
                      </div>
                      <p className="mt-1 text-sm">
                        {NUM(a.qty)}
                        {a.unit} · {a.date}
                      </p>
                      {a.type === "expiry" &&
                      a.expected_expiry_qty !== undefined ? (
                        <>
                          <p className="mt-2 text-sm">
                            기한 내 예상 사용{" "}
                            <b>
                              {NUM(a.expected_use_before_expiry_qty ?? 0)}
                              {a.unit}
                            </b>{" "}
                            · 예상 폐기{" "}
                            <b>
                              {NUM(a.expected_expiry_qty)}
                              {a.unit}
                            </b>
                          </p>
                          <details className="mt-2 text-xs">
                            <summary className="cursor-pointer">
                              로트별 사용·폐기 전망
                            </summary>
                            {(a.lots ?? []).map((l, k) => (
                              <p key={k} className="mt-1">
                                {l.lot_id} · {l.last_use_date}까지 · 보유{" "}
                                {NUM(l.current_qty)} / 사용{" "}
                                {NUM(l.expected_used_qty)} / 폐기{" "}
                                {NUM(l.expected_expiry_qty)}
                                {a.unit}
                              </p>
                            ))}
                          </details>
                        </>
                      ) : (
                        a.detail && <p className="mt-1 text-xs">{a.detail}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-3 text-xs text-slate-500">
                임박 수량 전체가 폐기되는 것은 아닙니다. 예상 사용·폐기는 기확정
                입고와 메뉴별 판매 제약을 반영하며, 신규 발주·이동·품질폐기는
                제외한 전망입니다.
              </p>
            </Card>
            <div className="mt-4">
              <Card title="식자재별 현재 재고와 오늘 예상 소요량">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b text-xs text-slate-500">
                        <th className="py-2">식자재</th>
                        <th>전일 마감</th>
                        <th>오늘 입고</th>
                        <th>입고 후 장부</th>
                        <th>예상 소요</th>
                        <th>가장 가까운 소비기한</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.ingredients
                        .filter(
                          (i) => i.predicted_today > 0 || i.current_stock > 0,
                        )
                        .sort(
                          (a, b) =>
                            b.predicted_today / (b.current_stock + 1) -
                            a.predicted_today / (a.current_stock + 1),
                        )
                        .map((i) => (
                          <tr
                            key={i.ingredient_id}
                            className="border-b border-slate-100"
                          >
                            <td className="py-2">{i.ingredient}</td>
                            <td>
                              {NUM(i.opening_stock ?? i.current_stock)}
                              {i.unit}
                            </td>
                            <td>
                              {NUM(i.received_today ?? 0)}
                              {i.unit}
                            </td>
                            <td>
                              {NUM(i.current_stock)}
                              {i.unit}
                            </td>
                            <td>
                              {NUM(i.predicted_today)}
                              {i.unit}
                            </td>
                            <td>{i.expiry_nearest ?? "재고 없음"}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  07시 입고 후 장부 기준입니다. 당일 실사조정과 이동 실행 전
                  수량입니다.
                </p>
              </Card>
            </div>
          </>
        )}
      </DashboardBoundary>
    </>
  );
}

export function ForecastPage() {
  return (
    <>
      <PageHeader
        title="판매 수요 예측"
        description="현재 서비스의 공통 EWMA·요일·공휴일·행사 보정을 적용하고 BOM으로 식자재 소요량을 계산합니다."
      />
      <DashboardBoundary>
        {(p) => (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={`${p.store_id} · 예측 메뉴 수요 (첫날)`}>
              <div className="space-y-2">
                {[...p.forecast]
                  .sort((a, b) => b.qty - a.qty)
                  .map((m) => (
                    <div
                      key={m.menu_id}
                      className="flex items-center justify-between border-b border-slate-100 pb-2 text-sm"
                    >
                      <span>{m.menu}</span>
                      <b>{NUM(m.qty)}개</b>
                    </div>
                  ))}
              </div>
            </Card>
            <Card title="BOM 변환 식자재 예상 소요 (첫날)">
              <div className="space-y-2">
                {p.ingredients
                  .filter((i) => i.predicted_today > 0)
                  .sort((a, b) => b.predicted_today - a.predicted_today)
                  .map((i) => (
                    <div
                      key={i.ingredient_id}
                      className="flex items-center justify-between border-b border-slate-100 pb-2 text-sm"
                    >
                      <span>{i.ingredient}</span>
                      <b>
                        {NUM(i.predicted_today)}
                        {i.unit}
                      </b>
                    </div>
                  ))}
              </div>
            </Card>
          </div>
        )}
      </DashboardBoundary>
    </>
  );
}
