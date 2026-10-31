import { createContext, useContext, useState, type ReactNode } from "react";
export type Role = "hub" | "member" | "independent";
export interface Account {
  id: string;
  role: Role;
  store: string;
  title: string;
  description: string;
}
// eslint-disable-next-line react-refresh/only-export-components
export const ACCOUNTS: Account[] = [
  {
    id: "HUB001",
    role: "hub",
    store: "S01",
    title: "허브 매장 관리자",
    description: "S01 · 그룹 재고와 공급을 함께 관리",
  },
  {
    id: "STORE002",
    role: "member",
    store: "S02",
    title: "허브 소속 매장",
    description: "S02 · 내 재고 확인과 허브 보충 요청",
  },
  {
    id: "SOLO003",
    role: "independent",
    store: "S03",
    title: "독립 운영 매장",
    description: "S03 · 공급사 정기발주와 긴급발주",
  },
];
interface Auth {
  account: Account | null;
  login: (id: string, password: string) => boolean;
  logout: () => void;
}
const Context = createContext<Auth | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(() => {
    try {
      return (
        ACCOUNTS.find(
          (a) => a.id === sessionStorage.getItem("cry-demo-account"),
        ) ?? null
      );
    } catch {
      return null;
    }
  });
  function login(id: string, password: string) {
    const found = ACCOUNTS.find((a) => a.id === id.trim().toUpperCase());
    if (!found || password !== "cry2026") return false;
    try {
      sessionStorage.setItem("cry-demo-account", found.id);
    } catch {
      /* memory-only session */
    }
    setAccount(found);
    return true;
  }
  function logout() {
    try {
      sessionStorage.removeItem("cry-demo-account");
    } catch {
      /* memory-only session */
    }
    setAccount(null);
  }
  return (
    <Context.Provider value={{ account, login, logout }}>
      {children}
    </Context.Provider>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error("AuthProvider required");
  return value;
}
