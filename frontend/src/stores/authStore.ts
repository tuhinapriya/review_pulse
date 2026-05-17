import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  authorId: string | null;
  authorName: string | null;
  setAuth: (token: string, authorId: string, authorName: string) => void;
  clearAuth: () => void;
}

// Persisted to localStorage so the user stays logged in across page refreshes.
// zustand/persist handles serialisation — no manual localStorage calls needed.
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      authorId: null,
      authorName: null,
      setAuth: (token, authorId, authorName) =>
        set({ token, authorId, authorName }),
      clearAuth: () => set({ token: null, authorId: null, authorName: null }),
    }),
    { name: "review-pulse-auth" }
  )
);
