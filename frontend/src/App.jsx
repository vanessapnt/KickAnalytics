import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ControllerPage  from './pages/ControllerPage';
import CameraPage      from './pages/CameraPage';
import IndexPage       from './pages/IndexPage';
import AuthPage        from './pages/AuthPage';

function ControllerGuard() {
  // import.meta.env.DEV is automatically true when I run `npm run dev` (Vite's development mode), and false when I run `npm run build` (production mode). This allows me to bypass the cookie check in development for easier testing.
  if (import.meta.env.DEV) return <ControllerPage />;
  const hasAccess = document.cookie.split(';').some(c => c.trim() === 'ka_page_access=controller');
  if (hasAccess) document.cookie = 'ka_page_access=; Path=/; Max-Age=0; SameSite=Lax';
  return hasAccess ? <ControllerPage /> : <Navigate to="/" replace />;
}

function CameraGuard() {
  if (import.meta.env.DEV) return <CameraPage />;
  const hasAccess = document.cookie.split(';').some(c => c.trim() === 'ka_page_access=camera');
  if (hasAccess) document.cookie = 'ka_page_access=; Path=/; Max-Age=0; SameSite=Lax';
  return hasAccess ? <CameraPage /> : <Navigate to="/" replace />;
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(() => !!localStorage.getItem('ka_user'));

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/"            element={loggedIn ? <IndexPage /> : <Navigate to="/auth" replace />} />
        <Route path="/auth"        element={loggedIn ? <Navigate to="/" replace /> : <AuthPage onAuth={() => setLoggedIn(true)} />} />
        <Route path="/controller"  element={<ControllerGuard />} />
        <Route path="/camera"      element={<CameraGuard />} />
        <Route path="*"            element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
