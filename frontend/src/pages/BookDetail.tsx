import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { fetchReviews, fetchTrends, draftResponse, type Review } from "@/lib/api";
import Badge from "@/components/Badge";

export default function BookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState<"reviews" | "trends">("reviews");

  const reviewsQuery = useQuery({
    queryKey: ["reviews", bookId, sentimentFilter, page],
    queryFn: () =>
      fetchReviews(bookId!, {
        sentiment: sentimentFilter || undefined,
        page,
        per_page: 20,
      }).then((r) => r.data),
    enabled: !!bookId,
  });

  const trendsQuery = useQuery({
    queryKey: ["trends", bookId],
    queryFn: () => fetchTrends(bookId!).then((r) => r.data),
    enabled: !!bookId && activeTab === "trends",
  });

  return (
    <div className="max-w-3xl">
      <div className="flex gap-3 mb-6">
        {(["reviews", "trends"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`text-sm font-medium pb-1 border-b-2 transition-colors capitalize
              ${activeTab === tab ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "reviews" && (
        <div>
          {/* Sentiment filter pills */}
          <div className="flex gap-2 mb-4">
            {["", "positive", "negative", "mixed"].map((s) => (
              <button
                key={s}
                onClick={() => { setSentimentFilter(s); setPage(1); }}
                className={`text-xs px-3 py-1 rounded-full border transition-colors
                  ${sentimentFilter === s
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border text-muted-foreground hover:text-foreground"}`}
              >
                {s || "All"}
              </button>
            ))}
          </div>

          {reviewsQuery.isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}

          <div className="space-y-3">
            {reviewsQuery.data?.reviews?.map((review: Review) => (
              <ReviewCard key={review.id} review={review} />
            ))}
          </div>

          {/* Page-based pagination */}
          {reviewsQuery.data?.has_next && (
            <button
              onClick={() => setPage((p) => p + 1)}
              className="mt-4 text-sm text-muted-foreground hover:text-foreground underline"
            >
              Load more
            </button>
          )}
        </div>
      )}

      {activeTab === "trends" && (
        <div>
          {trendsQuery.isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
          {trendsQuery.data && <TrendsChart data={trendsQuery.data} />}
        </div>
      )}
    </div>
  );
}

function ReviewCard({ review }: { review: Review }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [tone, setTone] = useState("professional");
  const [drafting, setDrafting] = useState(false);

  async function handleDraft() {
    setDrafting(true);
    try {
      const { data } = await draftResponse(review.id, tone);
      setDraft(data.draft);
    } finally {
      setDrafting(false);
    }
  }

  return (
    <div className="border rounded-lg p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{review.reviewer_name}</span>
        <div className="flex gap-1.5">
          <Badge
            label={review.sentiment}
            variant={review.sentiment === "mixed" ? "neutral" : (review.sentiment as "positive" | "negative")}
          />
          {review.is_actionable && <Badge label="actionable" />}
          {review.is_ai_generated && <Badge label="AI" variant="neutral" />}
        </div>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">{review.summary}</p>
      <p className="text-sm leading-relaxed">{review.body}</p>
      {review.themes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {review.themes.map((t) => (
            <Badge key={t} label={t} variant="neutral" />
          ))}
        </div>
      )}

      {/* Draft response — the P1 feature */}
      <div className="pt-2 border-t">
        <div className="flex items-center gap-2">
          <select
            value={tone}
            onChange={(e) => setTone(e.target.value)}
            className="text-xs border rounded px-2 py-1"
          >
            <option value="professional">Professional</option>
            <option value="warm">Warm</option>
            <option value="concise">Concise</option>
          </select>
          <button
            onClick={handleDraft}
            disabled={drafting}
            className="text-xs border rounded px-2 py-1 text-muted-foreground
                       hover:text-foreground hover:border-foreground disabled:opacity-40"
          >
            {drafting ? "Drafting…" : "✦ Draft reply"}
          </button>
        </div>
        {draft && (
          <div className="mt-2 p-3 bg-muted rounded text-sm whitespace-pre-wrap">{draft}</div>
        )}
      </div>
    </div>
  );
}

function TrendsChart({ data }: { data: { weekly: { week: string; positive: number; negative: number; neutral: number }[] } }) {
  return (
    <div>
      <h3 className="text-sm font-medium mb-3">Weekly sentiment</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data.weekly}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="week" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line type="monotone" dataKey="positive" stroke="#22c55e" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="negative" stroke="#ef4444" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="neutral" stroke="#94a3b8" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
