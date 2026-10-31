import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { FEATURES } from "@/features";
import { useAuth } from "@/lib/auth";
import { ScenarioProvider } from "@/lib/scenario";
import { LoginPage } from "@/pages/LoginPage";
export default function App() {
  const { account } = useAuth();
  if (!account) return <LoginPage />;
  const features = FEATURES.filter(
    (f) => !f.roles || f.roles.includes(account.role),
  );
  return (
    <ScenarioProvider key={account.id}>
      <Routes>
        <Route element={<Layout />}>
          {features.map((f) => (
            <Route key={f.path} path={f.path} element={f.element} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ScenarioProvider>
  );
}
