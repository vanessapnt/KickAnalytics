import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

function ExternalRedirect({ to }) {
  if (import.meta.env.DEV) return <div style={{padding:'20px'}}>Dev mode — go to <a href="/controller">/controller</a></div>;
  window.location.replace(to);
  return null;
}
import ControllerPage from './pages/ControllerPage';

function ControllerGuard() {
  // import.meta.env.DEV is automatically true when I run `npm run dev` (Vite's development mode), and false when I run `npm run build` (production mode). This allows me to bypass the cookie check in development for easier testing.
  if (import.meta.env.DEV) return <ControllerPage />;

  const hasAccess = document.cookie
    .split(';')
    .some(c => c.trim() === 'ka_page_access=controller');

  if (hasAccess) {
    document.cookie = 'ka_page_access=; Path=/; Max-Age=0; SameSite=Lax';
  }

  return hasAccess ? <ControllerPage /> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/controller" element={<ControllerGuard />} />
        <Route path="*" element={<ExternalRedirect to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
