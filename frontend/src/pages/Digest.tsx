import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Mail } from "lucide-react";
import { fetchMyDigest } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import Badge from "@/components/Badge";

export default function DigestPage() {
  const authorId = useAuthStore((s) => s.authorId);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["digest", authorId],
    queryFn: () => fetchMyDigest().then((r) => r.data),
    enabled: !!authorId,
  });

  if (isLoading) return <p className="text-muted-foreground">Loading digest…</p>;
  if (isError) {
    return <p className="text-sm text-destructive">Digest could not be loaded.</p>;
  }

  const headline = data?.headline ?? {
    new_reviews: 0,
    positive_pct: 0,
    actionable_count: 0,
    trend: data?.trend,
  };

  return (
    <div className="max-w-2xl space-y-8">
      <div className="flex items-center gap-2">
        <Mail size={20} className="text-muted-foreground" />
        <h1 className="text-xl font-semibold">Weekly Digest Preview</h1>
      </div>
      <p className="text-sm text-muted-foreground -mt-4">
        This is what your weekly email will contain. It updates as new reviews come in.
      </p>

      {/* Headline stats */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-3">
          This week
        </h2>
        <div className="grid grid-cols-3 gap-3">
          <StatCard label="New reviews" value={headline.new_reviews} />
          <StatCard label="Positive %" value={`${Math.round(headline.positive_pct)}%`} />
          <StatCard label="Actionable" value={headline.actionable_count} />
        </div>
        {headline.trend && (
          <p
            className={`mt-2 text-sm font-medium ${
              headline.trend === "improving"
                ? "text-green-700"
                : headline.trend === "declining"
                  ? "text-red-700"
                  : "text-muted-foreground"
            }`}
          >
            Trend: {headline.trend} vs last week
          </p>
        )}
      </section>

      {/* Top themes */}
      {data.top_themes?.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Top themes
          </h2>
          <div className="flex flex-wrap gap-2">
            {data.top_themes.map(({ theme, count }: { theme: string; count: number }) => (
              <span key={theme} className="text-sm flex items-center gap-1">
                <Badge label={theme} variant="neutral" />
                <span className="text-xs text-muted-foreground">×{count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Impactful reviews */}
      {data.impactful_reviews?.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Reviews to act on
          </h2>
          <div className="space-y-3">
            {data.impactful_reviews.map(
              (r: {
                id: string;
                book_id: string;
                book_title: string;
                reviewer_name: string;
                summary: string;
                sentiment: string;
              }) => (
                <div key={r.id} className="border rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <Link
                      to={`/books/${r.book_id}`}
                      className="text-xs text-muted-foreground hover:underline"
                    >
                      {r.book_title}
                    </Link>
                    <Badge
                      label={r.sentiment}
                      variant={r.sentiment as "positive" | "negative" | "neutral"}
                    />
                  </div>
                  <p className="text-sm font-medium">{r.reviewer_name}</p>
                  <p className="text-sm text-muted-foreground mt-0.5">{r.summary}</p>
                </div>
              )
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border rounded-lg p-4">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{label}</div>
    </div>
  );
}
