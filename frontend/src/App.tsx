import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { FEATURES } from '@/features'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {FEATURES.map((f) => (
          <Route key={f.path} path={f.path} element={f.element} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
