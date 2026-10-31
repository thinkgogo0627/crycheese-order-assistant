import { NavLink, Outlet } from 'react-router-dom'
import { FEATURES } from '@/features'
import { ApiStatus } from './ApiStatus'
import { ScenarioPanel } from './ScenarioPanel'

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="w-full shrink-0 border-b border-slate-200 bg-white p-4 md:w-64 md:border-b-0 md:border-r">
        <div className="mb-6">
          <p className="text-lg font-bold">식자재 발주 도우미</p>
          <ApiStatus />
        </div>
        <nav className="mb-6 flex gap-1 overflow-x-auto md:flex-col">
          {FEATURES.map(({ path, label, icon: Icon }) => (
            <NavLink key={path} to={path} end
              className={({ isActive }) =>
                `flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm ${
                  isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                }`}>
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <ScenarioPanel />
      </aside>
      <main className="flex-1 p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  )
}
