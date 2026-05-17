import { Link, Outlet, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, BarChart2, Search, Mail, LogOut } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

const nav = [
  { to: "/catalog", label: "My Books", icon: BookOpen },
  { to: "/compare", label: "Compare", icon: BarChart2 },
  { to: "/search", label: "Search", icon: Search },
  { to: "/digest", label: "Digest", icon: Mail },
];

export default function Layout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { authorName, clearAuth } = useAuthStore();

  function handleLogout() {
    clearAuth();
    queryClient.clear();
    navigate("/login");
  }

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r flex flex-col">
        <div className="px-5 py-4 border-b">
          <span className="font-semibold text-lg tracking-tight">ReviewPulse</span>
        </div>
        <nav className="flex-1 py-4 space-y-1 px-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium
                         text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            >
              <Icon size={16} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="px-4 py-3 border-t flex items-center justify-between">
          <span className="text-sm text-muted-foreground truncate">{authorName}</span>
          <button
            onClick={handleLogout}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Log out"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-8">
        <Outlet />
      </main>
    </div>
  );
}
