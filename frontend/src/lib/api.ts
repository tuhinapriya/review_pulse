import axios from "axios";
import { useAuthStore } from "@/stores/authStore";

// Base URL is empty in dev — Vite proxy forwards /api → http://localhost:8000
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  timeout: 30_000,
});

// Attach the JWT token from store to every outgoing request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401 clear the session — the token has expired or been revoked
apiClient.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().clearAuth();
    }
    return Promise.reject(error);
  }
);

// ─── Auth ────────────────────────────────────────────────────────────────────

export const register = (email: string, password: string, name: string) =>
  apiClient.post("/api/v1/register", { email, password, name });

export const login = (email: string, password: string) =>
  apiClient.post<{ access_token: string; author: { id: string; name: string; email: string } }>(
    "/api/v1/login",
    { email, password }
  );

// ─── Books ───────────────────────────────────────────────────────────────────

export const fetchBooks = () =>
  apiClient.get<BookWithStats[]>("/api/v1/authors/me/books");

export const addBook = (payload: { title: string; asin?: string }) =>
  apiClient.post<{ id: string }>("/api/v1/books", payload);

export const triggerIngest = (bookId: string) =>
  apiClient.post<Job>(`/api/v1/books/${bookId}/ingest`);

// ─── Jobs ────────────────────────────────────────────────────────────────────

export const fetchJob = (jobId: string) =>
  apiClient.get<Job>(`/api/v1/jobs/${jobId}`);

// ─── Reviews ─────────────────────────────────────────────────────────────────

export const fetchReviews = (bookId: string, params?: ReviewQueryParams) =>
  apiClient.get(`/api/v1/books/${bookId}/reviews`, { params });

export const draftResponse = (reviewId: string, tone: string) =>
  apiClient.post<DraftResponse>(`/api/v1/reviews/${reviewId}/draft-response`, { tone });

// ─── Trends ──────────────────────────────────────────────────────────────────

export const fetchTrends = (bookId: string) =>
  apiClient.get(`/api/v1/books/${bookId}/trends`);

// ─── Comparison ──────────────────────────────────────────────────────────────

export const compareBooks = (bookIds: string[]) =>
  apiClient.post<BookComparison[]>("/api/v1/books/compare", { book_ids: bookIds });

// ─── Search ──────────────────────────────────────────────────────────────────

export const semanticSearch = (query: string, k = 10) =>
  apiClient.post<SearchResult[]>("/api/v1/search", { query, k });

// ─── Activity ────────────────────────────────────────────────────────────────

export const fetchActivity = (authorId: string) =>
  apiClient.get(`/api/v1/authors/${authorId}/activity`);

// ─── Digest ──────────────────────────────────────────────────────────────────

export const fetchDigest = (authorId: string) =>
  apiClient.get(`/api/v1/authors/${authorId}/digest`);

export const fetchMyDigest = () =>
  apiClient.get("/api/v1/authors/me/digest");

// ─── Types ───────────────────────────────────────────────────────────────────

export interface BookWithStats {
  id: string;
  title: string;
  asin?: string;
  review_count: number;
  avg_rating: number;
  positive_pct: number;
  total_cost_usd?: number;
  last_ingested_at?: string;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "partial";
  total_reviews: number;
  processed_reviews: number;
  failed_reviews: number;
  error?: string;
  created_at: string;
  completed_at?: string;
}

export interface Review {
  id: string;
  reviewer_name: string;
  body: string;
  rating: number;
  sentiment: "positive" | "negative" | "mixed";
  themes: string[];
  summary: string;
  is_actionable: boolean;
  is_ai_generated: boolean;
  review_date?: string;
}

export interface ReviewQueryParams {
  sentiment?: string;
  is_actionable?: boolean;
  page?: number;
  per_page?: number;
  sort?: string;
}

export interface DraftResponse {
  review_id: string;
  draft: string;
  tone: string;
}

export interface BookComparison {
  id: string;
  title: string;
  review_count: number;
  avg_rating: number | string | null;
  positive_pct: number | string | null;
  mixed_pct: number | string | null;
  negative_pct: number | string | null;
  ai_flagged_rate: number | string | null;
  total_cost_usd: number | string | null;
  top_themes: Array<{ theme: string; count: number }>;
}

export interface SearchResult {
  review_id: string;
  book_id: string;
  book_title: string;
  reviewer_name: string;
  body: string;
  similarity: number;
}
