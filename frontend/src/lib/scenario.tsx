import { createContext, useContext, useState, type ReactNode } from "react";
import type { Scenario } from "@/types/api";
import { useAuth } from "./auth";
// eslint-disable-next-line react-refresh/only-export-components
export const DEFAULT_SCENARIO: Scenario = {
  as_of: "2026-10-01",
  store_id: "S01",
  horizon_days: 7,
  demand_multiplier: 1,
  delay_days: 0,
  service_level: 0.9,
  transfer_minutes: 30,
  transfer_cost: 0,
  can_split_pack: false,
  hub_store_ids: ["S01", "S02"],
  hub_host_store_id: "S01",
  hub_policy: "assigned",
  max_hubs: 1,
  chilled_capacity_liters: 200,
  frozen_capacity_liters: 200,
  ambient_capacity_liters: 150,
  hub_daily_cost: 12000,
};
// eslint-disable-next-line react-refresh/only-export-components
export const DATE_RANGE = { min: "2026-07-01", max: "2026-10-01" };
// eslint-disable-next-line react-refresh/only-export-components
export const STORES = [
  { id: "S01", name: "허브 매장" },
  { id: "S02", name: "허브 소속 매장" },
  { id: "S03", name: "독립 운영 매장" },
];
interface Ctx {
  scenario: Scenario;
  draft: Scenario;
  dirty: boolean;
  update: (p: Partial<Scenario>) => void;
  setAsOf: (date: string) => void;
  apply: () => void;
  reset: () => void;
}
const Context = createContext<Ctx | null>(null);
export function ScenarioProvider({ children }: { children: ReactNode }) {
  const { account } = useAuth();
  const initial: Scenario = {
    ...DEFAULT_SCENARIO,
    store_id: account?.store ?? "S01",
    ...(account?.role === "independent"
      ? {
          hub_store_ids: ["S03"],
          hub_host_store_id: null,
          max_hubs: 0,
          hub_policy: "none" as const,
        }
      : {}),
  };
  const [scenario, setScenario] = useState(initial);
  const [draft, setDraft] = useState(initial);
  const update = (p: Partial<Scenario>) => setDraft((s) => ({ ...s, ...p }));
  const setAsOf = (date: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date < DATE_RANGE.min || date > DATE_RANGE.max) return;
    setScenario((s) => ({ ...s, as_of: date }));
    setDraft((s) => ({ ...s, as_of: date }));
  };
  const reset = () => {
    setDraft(initial);
    setScenario(initial);
  };
  return (
    <Context.Provider
      value={{
        scenario,
        draft,
        dirty: JSON.stringify(draft) !== JSON.stringify(scenario),
        update,
        setAsOf,
        apply: () => setScenario(draft),
        reset,
      }}
    >
      {children}
    </Context.Provider>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function useScenario() {
  const value = useContext(Context);
  if (!value) throw new Error("ScenarioProvider required");
  return value;
}
