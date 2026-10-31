import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  ArrowRight,
  PackageCheck,
  CircleAlert,
  ClipboardList,
  Warehouse,
  Download,
  Truck,
  Check,
} from "lucide-react";
import type { ReactNode } from "react";
import { apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useScenario } from "@/lib/scenario";
import { usePlan } from "./PlannerPage";
import { Card, PageHeader } from "@/components/ui";
import type { HubResponse, HubOrder } from "@/types/api";
const num = (n: number) =>
  n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
const won = (n: number) => `${Math.round(n).toLocaleString("ko-KR")}원`;
function useHub() {
  const { scenario } = useScenario();
  return useQuery({
    queryKey: ["hub", scenario],
    queryFn: () => apiPost<HubResponse>("/api/hub", scenario),
  });
}
function SupplyBoundary({
  children,
}: {
  children: (p: HubResponse) => ReactNode;
}) {
  const q = useHub();
  if (q.isPending)
    return (
      <Card>
        <div className="loading-line" />
        <p className="muted">예측 수요와 발주·보관 조건을 계산하고 있습니다.</p>
      </Card>
    );
  if (q.isError)
    return (
      <Card>
        <p role="alert" className="error-text">
          계산을 불러오지 못했습니다. {q.error.message}
        </p>
        <button className="button secondary" onClick={() => q.refetch()}>
          다시 시도
        </button>
      </Card>
    );
  return <>{children(q.data)}</>;
}
function DraftTable({ rows, title }: { rows: HubOrder[]; title: string }) {
  const { scenario } = useScenario();
  function download() {
    const lines = [
      [
        "매장",
        "식자재",
        "발주일",
        "입고일",
        "포장 수량",
        "단위",
        "금액",
        "상태",
      ],
      ...rows.map((r) => [
        r.store_id,
        r.ingredient_name,
        r.order_date,
        r.arrival_date,
        r.order_qty,
        r.order_unit,
        r.amount,
        r.status,
      ]),
    ];
    const csv =
      "\uFEFF" +
      lines
        .map((row) =>
          row.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(","),
        )
        .join("\r\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `발주초안_${scenario.store_id}_${scenario.as_of}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <Card>
      <div className="section-heading">
        <h2>
          {title} <span className="count">{rows.length}</span>
        </h2>
        <button
          className="button secondary small"
          disabled={!rows.length}
          onClick={download}
        >
          <Download size={14} /> CSV 초안
        </button>
      </div>
      {!rows.length ? (
        <div className="empty-state">
          <PackageCheck size={28} />
          <b>생성된 발주 초안이 없습니다</b>
          <p>재고, 발주 요일, 다음 입고일과 최소 발주금액을 함께 확인하세요.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>식자재 / 공급사</th>
                <th>대상</th>
                <th>발주량</th>
                <th>입고 예정</th>
                <th>예상 금액</th>
                <th>검토 상태</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.store_id}-${r.ingredient_id}-${i}`}>
                  <td>
                    <b>{r.ingredient_name}</b>
                    <small>{r.supplier_id}</small>
                  </td>
                  <td>{r.store_id}</td>
                  <td>
                    {r.order_qty}
                    {r.order_unit}
                    <small>
                      사용 단위 {num(r.use_qty)}
                      {r.use_unit}
                    </small>
                  </td>
                  <td>{r.arrival_date}</td>
                  <td>{won(r.amount)}</td>
                  <td>
                    <span
                      className={`badge ${r.status === "DRAFT" ? "neutral" : "warning"}`}
                    >
                      {r.status === "DRAFT"
                        ? "검토 대기"
                        : r.status === "MIN_AMOUNT_REVIEW"
                          ? "최소금액 확인"
                          : "기한·용량 확인"}
                    </span>
                    <details>
                      <summary>계산 근거</summary>
                      <p className="hint">{r.basis}</p>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
export function OverviewPage() {
  const { account } = useAuth();
  const { scenario } = useScenario();
  const q = usePlan();
  const h = useHub();
  const p = q.data;
  const supply = h.data;
  const manager = account?.role === "hub";
  const shortages =
    supply?.shortages.filter((x) => manager || x.store_id === account?.store) ??
    [];
  const orders =
    supply?.store_orders.filter(
      (x) => manager || x.store_id === account?.store,
    ) ?? [];
  const expiry =
    p?.alerts.filter((x) => x.type === "expiry" || x.type === "expired") ?? [];
  const loading = !p || !supply;
  return (
    <>
      <div className="page-heading-row">
        <PageHeader
          title={
            account?.role === "hub"
              ? "우리 그룹의 준비 상태"
              : "우리 매장의 준비 상태"
          }
          description={`${account?.store} · ${account?.title} 작업 공간`}
        />
        <span className="date-label">
          {scenario.as_of.replaceAll("-", ".")}
          <span>판단 기준일</span>
        </span>
      </div>
      <section className="welcome-banner">
        <div>
          <span className="eyebrow yellow">READY FOR A GOOD DAY</span>
          <h2>
            {account?.role === "hub" ? (
              <>
                매장마다 필요한 재고,
                <br />
                한곳에서 살펴보세요.
              </>
            ) : account?.role === "member" ? (
              <>
                부족하기 전에 확인하고,
                <br />
                가까운 허브와 준비하세요.
              </>
            ) : (
              <>
                다음 입고까지 충분할까요?
                <br />
                우리 매장 발주를 점검하세요.
              </>
            )}
          </h2>
          <p>
            {account?.role === "independent"
              ? "허브 없이 정기발주와 외부 긴급발주로 운영합니다."
              : "S01 허브와 S02 매장을 연결합니다. S03 독립 매장은 포함하지 않습니다."}
          </p>
          <Link
            to={account?.role === "hub" ? "/hub" : "/orders"}
            className="button primary"
          >
            {account?.role === "hub" ? "그룹 공급안 확인" : "발주 초안 확인"}
            <ArrowUpRight size={17} />
          </Link>
        </div>
        <div className="banner-mark" aria-hidden="true">
          <Warehouse size={90} strokeWidth={1} />
          <span>
            {account?.role === "independent" ? "DIRECT" : "H01"}
            <small>
              {account?.role === "independent" ? "S03 · SUPPLIER" : "S01 + S02"}
            </small>
          </span>
        </div>
      </section>
      {(q.isError || h.isError) && (
        <div className="notice error" role="alert">
          일부 데이터를 불러오지 못했습니다.{" "}
          {q.error?.message ?? h.error?.message}
          <button
            className="text-button"
            onClick={() => {
              void q.refetch();
              void h.refetch();
            }}
          >
            다시 시도
          </button>
        </div>
      )}
      <div className="metric-grid">
        {[
          {
            label: manager ? "그룹 소속 매장" : "보유 식자재",
            value: loading
              ? "—"
              : manager
                ? `${scenario.hub_store_ids?.length ?? 0}`
                : `${p?.ingredients.filter((i) => i.current_stock > 0).length ?? 0}`,
            unit: manager ? "개 매장" : "품목",
            icon: PackageCheck,
            text: manager
              ? "S01 허브 · S02 소속 매장"
              : "판단일 입고 후 장부 기준",
          },
          {
            label: "예상 부족",
            value: loading
              ? "—"
              : `${new Set(shortages.map((x) => x.ingredient_id)).size}`,
            unit: "품목",
            icon: CircleAlert,
            text: account?.role === "independent" ? "정기입고 후 미해결 부족" : "정기입고·허브 공급 후 미해결",
          },
          {
            label: manager ? "허브 제약 확인" : "소비기한 주의",
            value: loading
              ? "—"
              : manager
                ? `${supply?.hub_orders.filter((x) => x.status !== "DRAFT").length ?? 0}`
                : `${new Set(expiry.map((x) => x.item)).size}`,
            unit: manager ? "건" : "품목",
            icon: ClipboardList,
            text: manager
              ? "허브 발주 최소금액 등 검토"
              : "로트별 기한·사용 전망 확인",
          },
          {
            label: manager ? "그룹 정기발주 초안" : "매장 정기발주 초안",
            value: loading ? "—" : `${orders.length}`,
            unit: "건",
            icon: Truck,
            text: loading
              ? "계산 중"
              : `예상 구매액 ${won(orders.reduce((s, x) => s + x.amount, 0))}`,
          },
        ].map(({ label, value, unit, icon: Icon, text }) => (
          <div className="metric-card" key={label}>
            <div>
              <span>{label}</span>
              <Icon size={18} />
            </div>
            <p>
              {value}
              <small>{unit}</small>
            </p>
            <span>{text}</span>
          </div>
        ))}
      </div>
      <div className="overview-grid">
        <Card>
          <div className="section-heading">
            <h2>지금 확인할 일</h2>
            <span className="badge warning">우선 확인</span>
          </div>
          <div className="task-list">
            <Link to="/inventory">
              <span className="task-number">01</span>
              <div>
                <b>부족·소비기한 위험 확인</b>
                <p>오래된 로트가 먼저 사용되는지 살펴보세요.</p>
              </div>
              <ArrowUpRight size={17} />
            </Link>
            <Link to={account?.role === "independent" ? "/emergency" : "/hub"}>
              <span className="task-number">02</span>
              <div>
                <b>
                  {account?.role === "independent"
                    ? "긴급발주 도착 전 공백 확인"
                    : "허브 공급 가능량과 보관 여력 확인"}
                </b>
                <p>
                  {account?.role === "independent"
                    ? "다음날 입고로 오늘의 판매손실을 회복할 수는 없습니다."
                    : "운송 30분에 준비·검수 시간을 더해 검토합니다."}
                </p>
              </div>
              <ArrowUpRight size={17} />
            </Link>
            <Link to="/orders">
              <span className="task-number">03</span>
              <div>
                <b>발주량·입고일·최소금액 검토</b>
                <p>추천은 초안입니다. 실제 전송 전 담당자가 확인하세요.</p>
              </div>
              <ArrowUpRight size={17} />
            </Link>
          </div>
        </Card>
        <Card>
          <div className="section-heading">
            <h2>오늘의 예상 메뉴 수요</h2>
            <Link to="/forecast" className="text-button">
              전체 보기 <ArrowRight size={13} />
            </Link>
          </div>
          {q.isPending ? (
            <p className="muted">수요 계산 중…</p>
          ) : !p ? (
            <p className="muted">연결 후 예측을 확인할 수 있습니다.</p>
          ) : (
            [...p.forecast]
              .sort((a, b) => b.qty - a.qty)
              .slice(0, 5)
              .map((m) => (
                <div className="demand-row" key={m.menu_id}>
                  <div>
                    <span>{m.menu}</span>
                    <b>{num(m.qty)}개</b>
                  </div>
                  <div className="bar-track">
                    <i
                      style={{
                        width: `${Math.min(100, (m.qty / Math.max(1, ...p.forecast.map((x) => x.qty))) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              ))
          )}
          <p className="hint">공통 EWMA 예측 · 실제 판매 실적이 아닙니다.</p>
        </Card>
      </div>
    </>
  );
}
export function SupplyPage({ view }: { view: "orders" | "hub" | "emergency" }) {
  const { account } = useAuth();
  const { scenario } = useScenario();
  const manager = account?.role === "hub";
  const title =
    view === "orders"
      ? "필요한 만큼, 정기발주"
      : view === "emergency"
        ? "남은 부족, 긴급발주 검토"
        : manager
          ? "허브 재고와 그룹 공급"
          : "우리 매장 허브 보충";
  return (
    <>
      <PageHeader
        title={title}
        description={
          view === "hub"
            ? "매장 간 직접 이동 없이 허브를 통해 공급하는 시나리오입니다."
            : "예측 수요, 유효 재고, 기확정 입고와 공급사 제약을 반영한 검토 초안입니다."
        }
      />
      <SupplyBoundary>
        {(p) => {
          const own = (r: { store_id: string }) =>
            manager || r.store_id === account?.store;
          const orders = p.store_orders.filter(own);
          const emergency = p.emergency_orders.filter(own);
          const transfers = p.transfers.filter(own);
          const shortages = p.shortages.filter(own);
          return (
            <div className="stack">
              <div
                className={`notice ${p.status === "FEASIBLE_SCENARIO" ? "" : "warning"}`}
              >
                <CircleAlert size={18} />
                <div>
                  <b>
                    {p.status === "FEASIBLE_SCENARIO"
                      ? "입력 조건을 충족하는 계산안입니다."
                      : "현재 조건을 모두 만족하는 계획이 없습니다."}
                  </b>
                  <p>
                    {manager
                      ? "그룹 전체"
                      : account?.role === "member"
                        ? "소속 그룹"
                        : "S03 단독"}
                    의 원가 가중 식자재 수요 충족률{" "}
                    {(p.fill_rate * 100).toFixed(1)}% · 목표{" "}
                    {(p.service_target * 100).toFixed(0)}%.{" "}
                    {p.status !== "FEASIBLE_SCENARIO" &&
                      "아래 결과는 문제 확인용이며 실행 가능한 추천안으로 보장하지 않습니다."}
                  </p>
                  {p.status !== "FEASIBLE_SCENARIO" && (
                    <p>
                      제약 확인: 최소금액 미달{" "}
                      {
                        p.store_orders
                          .concat(p.hub_orders)
                          .filter((x) => x.status === "MIN_AMOUNT_REVIEW")
                          .length
                      }
                      건 · 용량 미달{" "}
                      {p.groups.filter((g) => !g.capacity_ok).length}그룹 · 차량
                      여력 미달 {p.groups.filter((g) => !g.fleet_ok).length}그룹
                      · 거리 초과{" "}
                      {p.groups.flatMap((g) => g.outside_30_minutes).length}
                      매장. 그룹 내 각 매장의 목표 충족 여부도 검사합니다.
                    </p>
                  )}
                </div>
              </div>
              {view === "orders" && (
                <>
                  <div className="flow-strip">
                    <span className="current">정기발주</span>
                    <ArrowRight size={16} />
                    <span>
                      {account?.role === "independent"
                        ? "다음 입고까지 재고 점검"
                        : "허브 공급"}
                    </span>
                    <ArrowRight size={16} />
                    <span>외부 긴급발주</span>
                  </div>
                  <DraftTable
                    title={
                      manager
                        ? "그룹 매장 정기발주 초안"
                        : "우리 매장 정기발주 초안"
                    }
                    rows={orders}
                  />
                  {manager && (
                    <DraftTable
                      title="허브 공동 안전재고 발주 초안"
                      rows={p.hub_orders}
                    />
                  )}
                  <p className="hint">
                    {account?.role === "independent"
                      ? "S03의 예측 수요와 안전재고를 자체 확보합니다. 허브 공급과 매장 간 이동은 계산에서 제외합니다."
                      : "매장 기본 수요량을 일괄 축소하지 않습니다. 매장 대응 재고를 남기고, 안전재고 중 허브로 옮길 수 있는 비율을 비교합니다."}
                  </p>
                </>
              )}
              {view === "hub" && (
                <>
                  <Card>
                    <div className="section-heading">
                      <h2>{manager ? "그룹 운영 구조" : "소속 허브 안내"}</h2>
                      <span className="badge neutral">
                        {scenario.hub_policy === "auto"
                          ? "대안 탐색 모드"
                          : "H01 고정 운영"}
                      </span>
                    </div>
                    <div className="network-strip">
                      <div className="network-node hub">
                        <Warehouse size={24} />
                        <b>S01 · H01 허브</b>
                        <small>자체 영업분 제외 여유 공간</small>
                      </div>
                      <span className="network-edge">
                        →<small>운송 30분</small>
                      </span>
                      <div className="network-node">
                        <PackageCheck size={24} />
                        <b>S02 · 소속 매장</b>
                        <small>허브 보충 대상</small>
                      </div>
                    </div>
                    <p className="hint">
                      S03 독립 매장은 이 그룹과 재고·발주를 공유하지 않습니다.
                      준비 10분 + 검수 5분을 포함한 응답시간은 최대 45분
                      가정입니다.
                    </p>
                  </Card>
                  {manager && (
                    <div className="capacity-grid">
                      {(["chilled", "frozen", "ambient"] as const).map(
                        (zone, i) => {
                          const peak = p.groups.reduce(
                            (sum, g) => sum + (g.peak_liters[zone] ?? 0),
                            0,
                          );
                          const cap =
                            scenario[`${zone}_capacity_liters` as const] ?? 0;
                          return (
                            <Card key={zone}>
                              <div className="section-heading">
                                <h2>{["냉장", "냉동", "상온"][i]} 보관</h2>
                                {peak <= cap ? (
                                  <Check size={16} />
                                ) : (
                                  <CircleAlert size={16} />
                                )}
                              </div>
                              <p className="capacity-number">
                                {num(peak)}
                                <small> / {num(cap)} L</small>
                              </p>
                              <div
                                className={`bar-track ${peak > cap ? "danger" : ""}`}
                              >
                                <i
                                  style={{
                                    width: `${Math.min(100, (peak / Math.max(1, cap)) * 100)}%`,
                                  }}
                                />
                              </div>
                              <p className="hint">
                                입고 직후 최대 보관량 · 부피는 가정값
                              </p>
                            </Card>
                          );
                        },
                      )}
                    </div>
                  )}
                  <Card>
                    <div className="section-heading">
                      <h2>
                        {manager
                          ? "그룹 허브 공급 초안"
                          : "우리 매장 보충 요청 초안"}{" "}
                        <span className="count">{transfers.length}</span>
                      </h2>
                      <span className="badge warning">미전송</span>
                    </div>
                    {!transfers.length ? (
                      <div className="empty-state">
                        <Warehouse size={28} />
                        <b>현재 공급 가능한 허브 이동안이 없습니다</b>
                        <p>
                          부족이 없거나 허브 입고·용량·포장 제약으로 공급이
                          어려울 수 있습니다.
                        </p>
                      </div>
                    ) : (
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>공급일</th>
                              <th>경로</th>
                              <th>식자재</th>
                              <th>수량</th>
                              <th>응답시간</th>
                              <th>기존 소비기한</th>
                            </tr>
                          </thead>
                          <tbody>
                            {transfers.map((t, i) => (
                              <tr key={i}>
                                <td>{t.date}</td>
                                <td>
                                  {t.hub_id} → {t.store_id}
                                </td>
                                <td>{t.ingredient_name}</td>
                                <td>
                                  {num(t.qty)}
                                  {t.use_unit}
                                </td>
                                <td>{t.response_minutes}분</td>
                                <td>{t.last_use_date}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <p className="hint">
                      추천량을 보여주는 초안입니다. 요청 전송·승인·출고·수령은
                      아직 실행하지 않습니다.
                    </p>
                  </Card>
                  {manager && (
                    <>
                      <DraftTable
                        rows={p.hub_orders}
                        title="허브 재고 확보 발주안"
                      />
                      <Card>
                        <div className="section-heading">
                          <h2>무허브·허브 대안 비교</h2>
                          <span className="badge neutral">같은 수요 예측</span>
                        </div>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>허브 수</th>
                                <th>조건 충족</th>
                                <th>수요 충족률</th>
                                <th>모형 경제비용</th>
                                <th>물류비</th>
                                <th>예상 폐기 원가</th>
                              </tr>
                            </thead>
                            <tbody>
                              {p.alternatives.map((a) => (
                                <tr key={a.hub_count}>
                                  <td>
                                    {a.hub_count === 0
                                      ? "무허브"
                                      : `${a.hub_count}개`}
                                  </td>
                                  <td>
                                    <span
                                      className={`badge ${a.feasible ? "neutral" : "warning"}`}
                                    >
                                      {a.feasible ? "충족" : "미달"}
                                    </span>
                                  </td>
                                  <td>{(a.fill_rate * 100).toFixed(1)}%</td>
                                  <td>{won(a.economic_cost)}</td>
                                  <td>{won(a.logistics_cost)}</td>
                                  <td>{won(a.waste_cost)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="hint">
                          경제비용은 재고 수지·보유비·배송비·허브비·미충족
                          페널티를 포함한 모형 값이며 실제 절감액이 아닙니다.
                          고정 운영 모드에서는 무허브가 더 저렴해도 H01 운영
                          결과를 표시합니다.
                        </p>
                      </Card>
                    </>
                  )}
                </>
              )}
              {view === "emergency" && (
                <>
                  <div className="notice warning">
                    <Truck size={20} />
                    <div>
                      <b>긴급발주는 다음날 이후를 위한 보충입니다.</b>
                      <p>
                        입고 지연 조건을 추가 적용합니다. 당일 품절은 별도로
                        표시하며 긴급발주 효과를 현재 충족률에 합산하지
                        않습니다.
                      </p>
                    </div>
                  </div>
                  <DraftTable title="공급사 긴급발주 초안" rows={emergency} />
                  <Card title="입고·허브 공급 후 남는 부족">
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>예상일</th>
                            <th>매장</th>
                            <th>식자재</th>
                            <th>부족량</th>
                          </tr>
                        </thead>
                        <tbody>
                          {shortages.map((r, i) => (
                            <tr key={i}>
                              <td>{r.date}</td>
                              <td>{r.store_id}</td>
                              <td>{r.ingredient_name}</td>
                              <td>
                                {num(r.qty)}
                                {r.use_unit}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!shortages.length && (
                        <p className="muted">
                          현재 전망 기간의 미해결 부족이 없습니다.
                        </p>
                      )}
                    </div>
                  </Card>
                </>
              )}
              <details className="assumptions">
                <summary>계산 기준과 한계 확인</summary>
                <p>{p.forecast_basis}</p>
                {[...p.warnings, ...p.assumptions].map((a, i) => (
                  <p key={i}>· {a}</p>
                ))}
              </details>
            </div>
          );
        }}
      </SupplyBoundary>
    </>
  );
}
