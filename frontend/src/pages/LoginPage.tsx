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
          <span className="eyebrow yellow">STORE OPERATIONS</span>
          <h1>
            맛있는 하루는,
            <br />
            준비된 재고에서.
          </h1>
          <p>
            매장의 수요를 읽고, 필요한 만큼 준비합니다.
            <br />
            우리 매장에 맞는 재고·발주 관리를 시작하세요.
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
          CRYCHEESEBURGER · 재고·발주 의사결정 프로토타입
        </p>
      </section>
      <section className="login-form-side">
        <div className="login-form-wrap">
          <span className="eyebrow">WELCOME BACK</span>
          <h2>매장 관리 시작하기</h2>
          <p className="muted">하나의 입구, 역할에 맞는 작업 공간.</p>
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
          <p className="demo-note">
            합성 데이터로 동작하는 시연용 로그인입니다. 실제 계정 인증·접근 권한
            보안과 발주 전송은 포함하지 않습니다.
          </p>
        </div>
      </section>
    </div>
  );
}
