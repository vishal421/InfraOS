import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { DeviceListPage } from './pages/DeviceListPage'
import { DeviceDetailPage } from './pages/DeviceDetailPage'
import { LoginPage } from './pages/LoginPage'
import { AuthProvider, useAuth } from './auth/AuthContext'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DeviceListPage />} />
            <Route path="/devices/:deviceId" element={<DeviceDetailPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
