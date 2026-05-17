import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { semanticSearch, type SearchResult } from "@/lib/api";

export default function SearchPage() {
  const [query, setQuery] = useState("");

  const searchMutation = useMutation({
    mutationFn: (q: string) => semanticSearch(q, 15).then((r) => r.data),
  });

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) searchMutation.mutate(query.trim());
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold mb-4">Semantic Search</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Search across all reviews using natural language — "readers who struggled with pacing",
        "praise for world-building", etc.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="What are readers saying about…"
          className="flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <button
          type="submit"
          disabled={!query.trim() || searchMutation.isPending}
          className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm font-medium
                     hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
        >
          <Search size={14} />
          {searchMutation.isPending ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="space-y-3">
        {searchMutation.data?.map((result: SearchResult) => (
          <div key={result.review_id} className="border rounded-lg p-4">
            <div className="flex items-center justify-between mb-1">
              <Link
                to={`/books/${result.book_id}`}
                className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
              >
                {result.book_title}
              </Link>
              <span className="text-xs text-muted-foreground">
                {/* Similarity on a 0-1 scale — higher = more relevant to the query */}
                {Math.round(result.similarity * 100)}% match
              </span>
            </div>
            <p className="text-sm font-medium">{result.reviewer_name}</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{result.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
