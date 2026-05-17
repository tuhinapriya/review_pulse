import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/Login";
import RegisterPage from "@/pages/Register";
import CatalogPage from "@/pages/Catalog";
import BookDetailPage from "@/pages/BookDetail";
import ComparePage from "@/pages/Compare";
import SearchPage from "@/pages/Search";
import DigestPage from "@/pages/Digest";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/catalog" replace />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/books/:bookId" element={<BookDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/digest" element={<DigestPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
