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
import { Fragment, useId, useState, type ReactNode } from "react";
import { apiPost } from "@/lib/api";
import { applyOrderQuantity, orderDraftCsv, orderGroupKey, orderMinimumChecks } from "@/lib/editableOrderDraft";
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
        <p className="muted">공급 내역을 불러오고 있습니다.</p>
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
  return <EditableDraftTable key={JSON.stringify([scenario, rows])} rows={rows} title={title} />;
}
function EditableDraftTable({ rows, title }: { rows: HubOrder[]; title: string }) {
  const { scenario } = useScenario();
  const tableId = useId();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const edited = rows.map((row, i) => {
    const value = applyOrderQuantity(row, quantities[i] ?? String(row.order_qty));
    return value && { ...value, status: value.order_qty !== row.order_qty ? "수량 수정" : row.status };
  });
  const invalid = edited.some(row => row === null);
  const changed = rows.some((row, i) => edited[i]?.order_qty !== row.order_qty);
  const minimums = orderMinimumChecks(rows, edited);
  const downloadable = edited.filter((row): row is HubOrder => row !== null && row.order_qty > 0).map(row => {
    const group = minimums.find(value => value.key === orderGroupKey(row));
    return { ...row, order_total: group?.amount ?? row.amount,
      status: group?.below ? "MIN_AMOUNT_REVIEW" : row.status === "MIN_AMOUNT_REVIEW" ? "DRAFT" : row.status };
  });
  function download() {
    if (invalid || !downloadable.length) return;
    const csv = orderDraftCsv(downloadable);
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
          disabled={invalid || !downloadable.length}
          onClick={download}
        >
          <Download size={14} /> 발주 목록 내려받기
        </button>
      </div>
      {rows.length > 0 && <div className="draft-edit-summary">
        <span>발주 합계 <b>{invalid ? "수량 확인 필요" : won(downloadable.reduce((sum, row) => sum + row.amount, 0))}</b></span>
        {changed && <button type="button" className="text-button" onClick={() => setQuantities({})}>추천 수량으로 초기화</button>}
      </div>}
      {minimums.some(group => group.below) && <div className="draft-minimum-warning" role="status">
        {minimums.filter(group => group.below).map(group => <p key={group.key}>
          {group.store} · {group.supplier} · {group.date} <b>최소주문금액 미달</b>
        </p>)}
      </div>}
      {changed && <p className="hint draft-edit-note">재고 전망: 추천 수량 기준</p>}
      {!rows.length ? (
        <div className="empty-state">
          <PackageCheck size={28} />
          <b>발주할 품목이 없습니다</b>
          <p>재고, 발주 요일, 다음 입고일과 최소 발주금액을 함께 확인하세요.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="draft-table">
            <colgroup>
              <col style={{ width: "24%" }} />
              <col style={{ width: "8%" }} />
              <col style={{ width: "18%" }} />
              <col style={{ width: "17%" }} />
              <col style={{ width: "15%" }} />
              <col style={{ width: "18%" }} />
            </colgroup>
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
              {rows.map((r, i) => {
                const key = `${r.store_id}-${r.ingredient_id}-${r.order_date}-${i}`;
                const open = expandedRow === key;
                const detailId = `${tableId}-basis-${i}`;
                const value = edited[i];
                const modified = value !== null && value.order_qty !== r.order_qty;
                return <Fragment key={key}>
                <tr>
                  <td>
                    <b>{r.ingredient_name}</b>
                    <small>{r.supplier_id}</small>
                  </td>
                  <td>{r.store_id}</td>
                  <td>
                    <div className="draft-quantity-field">
                      <input type="number" inputMode="numeric" min={0} step={1}
                        value={quantities[i] ?? r.order_qty}
                        aria-label={`${r.store_id} ${r.ingredient_name} 발주 수량`}
                        aria-invalid={value === null}
                        aria-describedby={value === null ? `${tableId}-error-${i}` : undefined}
                        onChange={e => setQuantities(current => ({ ...current, [i]: e.target.value }))} />
                      <span>{r.order_unit}</span>
                    </div>
                    {value === null && <small id={`${tableId}-error-${i}`} className="draft-input-error">0 이상의 정수를 입력하세요.</small>}
                    <small>
                      추천 {r.order_qty}{r.order_unit} · {value ? num(value.use_qty) : "—"}
                      {r.use_unit}
                    </small>
                  </td>
                  <td>{r.arrival_date}</td>
                  <td>{value ? won(value.amount) : "—"}</td>
                  <td>
                    <span
                      className={`badge ${modified || (r.status !== "DRAFT" && r.status !== "MIN_AMOUNT_REVIEW") ? "warning" : "neutral"}`}
                    >
                      {modified
                        ? value.order_qty === 0 ? "발주 제외" : "수량 수정"
                        : r.status === "DRAFT" || r.status === "MIN_AMOUNT_REVIEW"
                        ? "검토 대기"
                        : "기한·용량 확인"}
                    </span>
                    <button type="button" className="draft-basis-toggle"
                      aria-expanded={open} aria-controls={detailId}
                      onClick={() => setExpandedRow(open ? null : key)}>
                      {open ? "근거 닫기" : "계산 근거"}
                    </button>
                  </td>
                </tr>
                <tr id={detailId} hidden={!open} className="draft-basis-row">
                  <td colSpan={6}><p>{modified && <b>추천 수량 기준 · </b>}{r.basis}</p></td>
                </tr>
                </Fragment>;
              })}
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
              ? "허브 운영 현황"
              : "매장 운영 현황"
          }
          description={`${account?.store} · ${account?.title}`}
        />
        <span className="date-label">
          {scenario.as_of.replaceAll("-", ".")}
          <span>판단 기준일</span>
        </span>
      </div>
      <section className="welcome-banner">
        <div>
          <span className="eyebrow yellow">오늘의 업무</span>
          <h2>
            {account?.role === "hub"
              ? "허브 공급·발주"
              : account?.role === "member"
                ? "매장 발주·보충"
                : "정기·긴급 발주"}
          </h2>
          <p>
            {account?.role === "independent"
              ? "정기발주 · 긴급발주"
              : "허브 재고 · 매장별 공급 예정 물량"}
          </p>
          <Link
            to={account?.role === "hub" ? "/hub" : "/orders"}
            className="button primary"
          >
            {account?.role === "hub" ? "공급 내역 보기" : "발주 초안 확인"}
            <ArrowUpRight size={17} />
          </Link>
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
              </div>
              <ArrowUpRight size={17} />
            </Link>
            <Link to="/orders">
              <span className="task-number">03</span>
              <div>
                <b>발주량·입고일·최소금액 검토</b>
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
      ? "정기발주"
      : view === "emergency"
        ? "긴급발주"
        : manager
          ? "허브 공급"
          : "허브 보충";
  return (
    <>
      <PageHeader
        title={title}
        description={
          view === "hub"
            ? "최소 주문 기준을 맞추기 어려운 매장을 위해 대형 점포를 공동 구매 거점인 허브로 운영합니다. 여러 매장의 물량을 함께 주문한 뒤, 필요한 만큼 각 매장으로 나눠 보냅니다."
            : "발주할 품목과 수량, 입고 예정일을 확인합니다."
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
                </>
              )}
              {view === "hub" && (
                <>
                  <Card>
                    <div className="section-heading">
                      <h2>{manager ? "공급 경로" : "공급 허브"}</h2>
                      <span className="badge neutral">
                        {scenario.hub_policy === "auto"
                          ? "허브 자동 선택"
                          : "H01"}
                      </span>
                    </div>
                    <div className="network-strip">
                      <div className="network-node hub">
                        <Warehouse size={24} />
                        <b>S01 · 공급 허브</b>
                        <small>H01 · 공동 재고 보관</small>
                      </div>
                      <span className="network-edge">
                        →<small>운송 30분</small>
                      </span>
                      <div className="network-node">
                        <PackageCheck size={24} />
                        <b>S02 · 공급 매장</b>
                        <small>허브 재고 보충</small>
                      </div>
                    </div>
                    <p className="hint">
                      예상 소요시간 45분 · 준비 10분 + 운송 30분 + 검수 5분
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
                                입고 후 최대 예상량 · 추정 부피
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
                          ? "매장별 공급 예정"
                          : "보충 예정 물량"}{" "}
                        <span className="count">{transfers.length}</span>
                      </h2>
                      <span className="badge warning">담당자 확인 전</span>
                    </div>
                    {!transfers.length ? (
                      <div className="empty-state">
                        <Warehouse size={28} />
                        <b>허브 공급 예정 물량이 없습니다</b>
                        <p>
                          부족 품목이 있다면 허브 재고와 입고일을 확인해 주세요.
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
                              <th>예상 소요시간</th>
                              <th>소비기한</th>
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
                      예상 물량입니다. 출고 전 상대 매장과 수량·소비기한을 확인해 주세요.
                    </p>
                  </Card>
                  {manager && (
                    <>
                      <DraftTable
                        rows={p.hub_orders}
                        title="허브 재고 확보 발주안"
                      />
                      <details className="detail-section">
                        <summary>허브 운영안 비교</summary>
                        <Card>
                        <div className="section-heading">
                          <h2>비용·공급 비교</h2>
                          <span className="badge neutral">동일 수요 기준</span>
                        </div>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>허브 수</th>
                                <th>조건 충족</th>
                                <th>수요 충족률</th>
                                <th>계산 비용</th>
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
                        </Card>
                      </details>
                    </>
                  )}
                </>
              )}
              {view === "emergency" && (
                <>
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
            </div>
          );
        }}
      </SupplyBoundary>
    </>
  );
}
