import { cn } from "@/lib/utils";

interface BadgeProps {
  label: string;
  variant?: "positive" | "negative" | "neutral" | "default";
  className?: string;
}

const variantStyles: Record<string, string> = {
  positive: "bg-green-100 text-green-800",
  negative: "bg-red-100 text-red-800",
  neutral: "bg-slate-100 text-slate-700",
  default: "bg-secondary text-secondary-foreground",
};

/**
 * Tiny pill badge used for sentiment labels and themes.
 * Using colour-coding here matches reader mental models: green = good, red = bad.
 */
export default function Badge({ label, variant = "default", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variantStyles[variant],
        className
      )}
    >
      {label}
    </span>
  );
}
