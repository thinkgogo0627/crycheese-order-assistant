import { useQuery } from "@tanstack/react-query";
import { apiGet, USE_MOCK } from "@/lib/api";
import type { HealthResponse } from "@/types/api";

// eslint-disable-next-line react-refresh/only-export-components
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<HealthResponse>("/health"),
    refetchInterval: 60_000,
  });
}

export function ApiStatus() {
  const { isPending, isError, data } = useHealth();
  const [color, label] = isPending
    ? ["bg-amber-400", "연결 중"]
    : isError || !data?.ok
      ? ["bg-red-500", "서버 연결 실패"]
      : ["bg-emerald-500", USE_MOCK ? "더미 데이터" : "서버 연결됨"];
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-600">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
