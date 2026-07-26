import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

interface AuthState {
  token: string | null
  username: string | null
  role: string | null
}

interface AuthContextValue extends AuthState {
  login: (token: string, username: string, role: string) => void
  logout: () => void
}

const STORAGE_KEY = 'infraos_auth'

const AuthContext = createContext<AuthContextValue | null>(null)

function loadStored(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { token: null, username: null, role: null }
    return JSON.parse(raw)
  } catch {
    return { token: null, username: null, role: null }
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(loadStored)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  const login = (token: string, username: string, role: string) => setState({ token, username, role })
  const logout = () => setState({ token: null, username: null, role: null })

  return <AuthContext.Provider value={{ ...state, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function getStoredToken(): string | null {
  return loadStored().token
}
