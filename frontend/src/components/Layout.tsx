import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LogOut, ArrowUpRight, SlidersHorizontal } from "lucide-react";
import { FEATURES } from "@/features";
import { useAuth } from "@/lib/auth";
import { useScenario } from "@/lib/scenario";
import { ApiStatus } from "./ApiStatus";
import { ScenarioPanel } from "./ScenarioPanel";
export function Layout() {
  const { account, logout } = useAuth();
  const { scenario } = useScenario();
  const location = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const features = FEATURES.filter(
    (f) => !f.roles || (account && f.roles.includes(account.role)),
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="sidebar-logo"
          href="https://www.crycheeseburger.com/"
          target="_blank"
          rel="noreferrer"
        >
          <img src="/brand/crycheese-logo.webp" alt="크라이치즈버거" />
          <ArrowUpRight size={15} />
        </a>
        <div className="workspace-label">
          STORE OPERATIONS <span>DEMO</span>
        </div>
        <nav aria-label="주 메뉴">
          {features.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end
              className={({ isActive }) =>
                `nav-item ${isActive ? "active" : ""}`
              }
            >
              <Icon size={18} />
              {label}
              <span className="nav-dot" />
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <p className="sidebar-note">
            필요한 만큼 준비하고,
            <br />
            함께 낭비를 줄입니다.
          </p>
          <div className="account-footer">
            <span className="avatar">{account?.store.slice(-2)}</span>
            <div>
              <b>{account?.title}</b>
              <small>
                {account?.id} · {account?.store}
              </small>
            </div>
            <button onClick={logout} aria-label="로그아웃" title="로그아웃">
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="breadcrumb">매장 운영</span>
            <span className="breadcrumb-separator">/</span>
            <b>{features.find((f) => f.path === location.pathname)?.label}</b>
          </div>
          <div className="topbar-right">
            <ApiStatus />
            <span className="store-chip">
              {scenario.store_id} ·{" "}
              {account?.role === "independent" ? "독립 운영" : "H01 그룹"}
            </span>
          </div>
        </header>
        <div className="workspace-content">
          <div className="context-strip">
            <span>
              <i /> 합성 데이터 시뮬레이션 · {scenario.as_of} 기준 ·{" "}
              {scenario.horizon_days}일 전망
            </span>
            <details className="scenario-popover">
              <summary>
                <SlidersHorizontal size={15} /> 분석 조건
              </summary>
              <ScenarioPanel />
            </details>
          </div>
          <main id="main-content">
            <Outlet />
          </main>
          <footer className="workspace-footer">
            <span>CRYCHEESEBURGER OPERATIONS</span>
            <span>모든 발주·공급 결과는 실행 전 검토할 초안입니다.</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
