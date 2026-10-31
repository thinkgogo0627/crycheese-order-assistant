import { useHealth } from '@/components/ApiStatus'
import { Card, JsonView, PageHeader } from '@/components/ui'
import { API_URL, USE_MOCK } from '@/lib/api'
import { useScenario } from '@/lib/scenario'

export function StatusPage() {
  const { data, error, isPending } = useHealth()
  const { scenario } = useScenario()
  return (
    <>
      <PageHeader title="연결 상태" description="백엔드 연결과 데이터 로딩을 확인합니다." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="백엔드">
          <p className="text-sm">주소: <code>{USE_MOCK ? '(더미 데이터 모드)' : API_URL || '(미설정)'}</code></p>
          {isPending && <p className="mt-2 text-sm text-slate-500">불러오는 중…</p>}
          {error && <p className="mt-2 text-sm text-red-600">{error.message}</p>}
          {data && (
            <table className="mt-3 w-full text-sm">
              <tbody>
                {Object.entries(data.tables).map(([name, rows]) => (
                  <tr key={name} className="border-t border-slate-100">
                    <td className="py-1 font-mono text-xs">{name}</td>
                    <td className="py-1 text-right">{rows.toLocaleString()}행</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="현재 조건 (API 요청 본문)">
          <JsonView value={scenario} />
        </Card>
      </div>
    </>
  )
}
