import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchBooks, compareBooks, type BookWithStats, type BookComparison } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import Badge from "@/components/Badge";

export default function ComparePage() {
  const authorId = useAuthStore((s) => s.authorId);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data: books } = useQuery({
    queryKey: ["books", authorId],
    queryFn: () => fetchBooks().then((r) => r.data),
    enabled: !!authorId,
  });

  const compareMutation = useMutation({
    mutationFn: () => compareBooks(Array.from(selected)),
  });

  function toggleBook(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="max-w-4xl">
      <h1 className="text-xl font-semibold mb-4">Compare Books</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Select 2–10 books to view a side-by-side breakdown of sentiment, themes, and AI-generated
        review rates.
      </p>

      {/* Selection checkboxes */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-6">
        {books?.map((book: BookWithStats) => (
          <label
            key={book.id}
            className={`flex items-center gap-2 border rounded-md p-3 cursor-pointer text-sm transition-colors
              ${selected.has(book.id) ? "border-primary bg-accent" : "hover:bg-muted"}`}
          >
            <input
              type="checkbox"
              checked={selected.has(book.id)}
              onChange={() => toggleBook(book.id)}
              className="rounded"
            />
            <span className="truncate">{book.title}</span>
          </label>
        ))}
      </div>

      <button
        disabled={selected.size < 2 || compareMutation.isPending}
        onClick={() => compareMutation.mutate()}
        className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm font-medium
                   hover:opacity-90 disabled:opacity-50"
      >
        {compareMutation.isPending ? "Comparing…" : "Compare"}
      </button>

      {compareMutation.isError && (
        <p className="mt-4 text-sm text-red-700">
          Could not compare those books. Please try again.
        </p>
      )}

      {/* Results */}
      {compareMutation.data && (
        <div className="mt-8 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Book</th>
                <th className="py-2 pr-4 font-medium">Avg ★</th>
                <th className="py-2 pr-4 font-medium">Positive</th>
                <th className="py-2 pr-4 font-medium">Negative</th>
                <th className="py-2 pr-4 font-medium">AI %</th>
                <th className="py-2 font-medium">Top themes</th>
              </tr>
            </thead>
            <tbody>
              {compareMutation.data.data.map((row: BookComparison) => (
                <tr key={row.id} className="border-b">
                  <td className="py-3 pr-4 font-medium">{row.title}</td>
                  <td className="py-3 pr-4">{formatRating(row.avg_rating)}</td>
                  <td className="py-3 pr-4 text-green-700">{formatPercent(row.positive_pct)}</td>
                  <td className="py-3 pr-4 text-red-700">{formatPercent(row.negative_pct)}</td>
                  <td className="py-3 pr-4">{formatPercent(row.ai_flagged_rate)}</td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-1">
                      {row.top_themes.slice(0, 3).map((t) => (
                        <Badge key={t.theme} label={t.theme} variant="neutral" />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatRating(value: number | string | null | undefined): string {
  if (value == null) return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(1) : "—";
}

function formatPercent(value: number | string | null | undefined): string {
  if (value == null) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return `${Math.round(numeric * 100)}%`;
}
