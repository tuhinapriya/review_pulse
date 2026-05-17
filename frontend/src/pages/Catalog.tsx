import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import {
  fetchBooks,
  addBook,
  triggerIngest,
  fetchJob,
  type BookWithStats,
  type Job,
} from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";

const FINAL_JOB_STATUSES = new Set<Job["status"]>(["completed", "partial", "failed"]);

export default function CatalogPage() {
  const qc = useQueryClient();
  const authorId = useAuthStore((s) => s.authorId);
  const [showAdd, setShowAdd] = useState(false);
  const [title, setTitle] = useState("");
  const [asin, setAsin] = useState("");
  const [ingestingBookId, setIngestingBookId] = useState<string | null>(null);
  const [jobByBookId, setJobByBookId] = useState<Record<string, Job>>({});

  const { data: books, isLoading } = useQuery({
    queryKey: ["books", authorId],
    queryFn: () => fetchBooks().then((r) => r.data),
    enabled: !!authorId,
  });

  const addMutation = useMutation({
    mutationFn: () => addBook({ title, asin: asin || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["books", authorId] });
      setShowAdd(false);
      setTitle("");
      setAsin("");
    },
  });

  const ingestMutation = useMutation({
    mutationFn: (bookId: string) => triggerIngest(bookId).then((r) => r.data),
    onMutate: (bookId) => {
      setIngestingBookId(bookId);
      setJobByBookId((jobs) => {
        const next = { ...jobs };
        delete next[bookId];
        return next;
      });
    },
    onSuccess: async (job, bookId) => {
      setJobByBookId((jobs) => ({ ...jobs, [bookId]: job }));
      let latest = job;
      while (!FINAL_JOB_STATUSES.has(latest.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        latest = (await fetchJob(latest.id)).data;
        setJobByBookId((jobs) => ({ ...jobs, [bookId]: latest }));
      }
      await qc.invalidateQueries({ queryKey: ["books", authorId] });
      setIngestingBookId(null);
    },
    onError: (_error, bookId) => {
      setIngestingBookId((current) => (current === bookId ? null : current));
    },
  });

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">My Books</h1>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 bg-primary text-primary-foreground
                     rounded-md px-3 py-1.5 text-sm font-medium hover:opacity-90"
        >
          <Plus size={14} /> Add book
        </button>
      </div>

      {/* Add book form */}
      {showAdd && (
        <div className="mb-6 border rounded-lg p-4 max-w-md">
          <h2 className="font-medium mb-3 text-sm">Add a new book</h2>
          <div className="space-y-3">
            <input
              placeholder="Book title *"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <input
              placeholder="Amazon ASIN (optional)"
              value={asin}
              onChange={(e) => setAsin(e.target.value)}
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <div className="flex gap-2">
              <button
                disabled={!title || addMutation.isPending}
                onClick={() => addMutation.mutate()}
                className="bg-primary text-primary-foreground rounded px-3 py-1.5 text-sm
                           hover:opacity-90 disabled:opacity-50"
              >
                {addMutation.isPending ? "Adding…" : "Add"}
              </button>
              <button
                onClick={() => setShowAdd(false)}
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Book grid */}
      {!books?.length ? (
        <p className="text-muted-foreground text-sm">No books yet. Add one to get started.</p>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
          {books.map((book: BookWithStats) => (
            <BookCard
              key={book.id}
              book={book}
              onIngest={() => ingestMutation.mutate(book.id)}
              ingesting={ingestingBookId === book.id}
              job={jobByBookId[book.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BookCard({
  book,
  onIngest,
  ingesting,
  job,
}: {
  book: BookWithStats;
  onIngest: () => void;
  ingesting: boolean;
  job?: Job;
}) {
  const statusText = getIngestStatusText(job, ingesting);

  return (
    <div className="border rounded-lg p-4 flex flex-col gap-3">
      <div>
        <Link
          to={`/books/${book.id}`}
          className="font-medium hover:underline text-sm leading-snug"
        >
          {book.title}
        </Link>
        {book.asin && (
          <p className="text-xs text-muted-foreground mt-0.5">ASIN: {book.asin}</p>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <Stat label="Reviews" value={book.review_count} />
        <Stat label="Avg ★" value={formatRating(book.avg_rating)} />
        <Stat
          label="Positive"
          value={formatPercent(book.positive_pct)}
        />
      </div>

      <button
        onClick={onIngest}
        disabled={ingesting}
        className="flex items-center justify-center gap-1.5 border rounded px-2 py-1.5
                   text-xs text-muted-foreground hover:text-foreground hover:border-foreground
                   transition-colors disabled:opacity-40"
      >
        <RefreshCw size={11} className={ingesting ? "animate-spin" : ""} />
        {statusText}
      </button>
    </div>
  );
}

function getIngestStatusText(job: Job | undefined, ingesting: boolean): string {
  if (!job) return ingesting ? "Starting…" : "Ingest reviews";
  if (job.status === "queued") return "Queued…";
  if (job.status === "running") {
    const total = job.total_reviews || 10;
    return `Ingesting ${job.processed_reviews}/${total}`;
  }
  if (job.status === "completed") return `Ingested ${job.processed_reviews}`;
  if (job.status === "partial") return `Partial ${job.processed_reviews}/${job.total_reviews}`;
  return "Ingest failed";
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

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-muted rounded p-1.5">
      <div className="font-semibold">{value}</div>
      <div className="text-muted-foreground mt-0.5">{label}</div>
    </div>
  );
}
