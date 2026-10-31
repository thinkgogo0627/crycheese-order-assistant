import { Card, JsonView, PageHeader } from '@/components/ui'
import { useScenario } from '@/lib/scenario'

// 기능이 확정되기 전 자리표시 화면. 실제 화면을 만들면 features.tsx에서 교체한다.
export function Placeholder({ title, description }: { title: string; description: string }) {
  const { scenario } = useScenario()
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card title="준비 중">
        <p className="mb-4 text-sm text-slate-600">
          이 화면은 아래 조건으로 백엔드에 요청을 보내게 됩니다.
        </p>
        <JsonView value={scenario} />
      </Card>
    </>
  )
}
