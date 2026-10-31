# frontend

Vite + React + TypeScript + Tailwind. 배포: Vercel.

## 로컬 실행
```bash
cd frontend
npm install
cp .env.example .env.local   # VITE_API_URL 수정 (백엔드 없이 하려면 VITE_USE_MOCK=true)
npm run dev                  # http://localhost:5173
```

## 구조
- `src/features.tsx` — 화면 목록. 기능 추가·삭제는 여기 한 곳만 수정
- `src/lib/scenario.tsx` — 사이드바 조건(기준일·매장·수요 배율 등), 모든 화면이 공유
- `src/lib/api.ts` — `apiGet` / `apiPost`. 주소는 `VITE_API_URL`
- `src/lib/mocks.ts` — 백엔드 준비 전 더미 응답
- `src/types/api.ts` — 백엔드와 맞출 타입

## 새 화면 붙이는 법
1. `src/pages/Xxx.tsx` 작성. 데이터는
   `useQuery({ queryKey: ['xxx', scenario], queryFn: () => apiPost('/api/xxx', scenario) })`
2. `src/features.tsx`의 Placeholder를 새 컴포넌트로 교체

## Vercel 배포
- Import Git Repository → Root Directory: `frontend` (Vite 자동 인식)
- Environment Variables: `VITE_API_URL` = Railway 주소 (끝에 `/` 없이)
- 환경변수를 바꾼 뒤에는 Redeploy 필요 (빌드 시점에 주입됨)
