import { useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  Warehouse,
  Store,
  MapPin,
  ArrowRight,
} from "lucide-react";
import { ACCOUNTS, useAuth } from "@/lib/auth";
export function LoginPage() {
  const { login } = useAuth();
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!login(id, password))
      setError(
        "아이디와 비밀번호를 확인해 주세요. 시연 비밀번호는 cry2026입니다.",
      );
  }
  return (
    <div className="login-shell">
      <section className="login-story">
        <a
          href="https://www.crycheeseburger.com/"
          target="_blank"
          rel="noreferrer"
          className="brand-link"
        >
          <img src="/brand/crycheese-logo.webp" alt="크라이치즈버거" />
          <ArrowUpRight size={18} />
        </a>
        <div className="login-copy">
          <span className="eyebrow yellow">크라이치즈버거</span>
          <h1>재고·발주 관리</h1>
          <p>
            품목별 재고, 입고일, 허브 공급 내역을 확인합니다.
            <br />
            담당 매장 계정으로 로그인해 주세요.
          </p>
          <div className="story-line">
            <span>01 수요 예측</span>
            <ArrowRight size={16} />
            <span>02 재고 확인</span>
            <ArrowRight size={16} />
            <span>03 발주 판단</span>
          </div>
        </div>
        <p className="login-foot">
          합성 자료를 사용하는 시연 화면입니다.
        </p>
      </section>
      <section className="login-form-side">
        <div className="login-form-wrap">
          <h2>매장 로그인</h2>
          <p className="muted">아래에서 시연 계정을 선택할 수 있습니다.</p>
          <form onSubmit={submit} className="login-form">
            <label>
              아이디
              <input
                autoComplete="username"
                placeholder="매장 아이디를 입력하세요"
                value={id}
                onChange={(e) => {
                  setId(e.target.value);
                  setError("");
                }}
                required
              />
            </label>
            <label>
              비밀번호
              <input
                type="password"
                autoComplete="current-password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error && (
              <p role="alert" className="error-text">
                {error}
              </p>
            )}
            <button className="button primary" type="submit">
              로그인 <ArrowRight size={18} />
            </button>
          </form>
          <div className="demo-divider">
            <span>시연 계정 선택</span>
            <span>공통 비밀번호 · cry2026</span>
          </div>
          <div className="account-list">
            {ACCOUNTS.map((a, i) => {
              const Icon = [Warehouse, Store, MapPin][i];
              return (
                <button
                  key={a.id}
                  className={`account-choice ${id === a.id ? "selected" : ""}`}
                  onClick={() => {
                    setId(a.id);
                    setPassword("cry2026");
                    setError("");
                  }}
                >
                  <Icon size={20} />
                  <span>
                    <b>{a.title}</b>
                    <small>{a.description}</small>
                  </span>
                  <code>{a.id}</code>
                </button>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
