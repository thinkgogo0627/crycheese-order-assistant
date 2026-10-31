import { MOCKS } from './mocks'
import type { ApiErrorBody } from '@/types/api'

export const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (USE_MOCK) {
    if (path in MOCKS) return structuredClone(MOCKS[path]) as T
    throw new ApiError(`mock 없음: ${path}`, 404)
  }
  if (!API_URL) throw new ApiError('VITE_API_URL이 설정되지 않았습니다', 0)

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null
    throw new ApiError(body?.error?.message ?? body?.detail ?? `요청 실패 (${res.status})`, res.status)
  }
  return res.json() as Promise<T>
}

export const apiGet = <T>(path: string) => request<T>(path)
export const apiPost = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })
