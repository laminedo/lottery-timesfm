"use client";

import { RefreshCw } from "lucide-react";

import { useApi, type Health } from "@/lib/api";
import { IS_STATIC, REPO_URL } from "@/lib/env";

/** Shown only on the hosted site: how fresh its data is and where the model actually runs. */
export function DemoNotice() {
  const { data } = useApi<Health>(IS_STATIC ? "/api/health" : null);
  if (!IS_STATIC) return null;
  const updated = data?.exported_at
    ? new Date(data.exported_at).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : null;
  return (
    <aside aria-label="About this site" className="border-b bg-card">
      <div className="mx-auto flex w-full max-w-6xl items-start gap-2.5 px-4 py-2.5 text-xs leading-relaxed text-muted-foreground sm:px-6 sm:text-[0.8rem]">
        <RefreshCw aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
        <p>
          <span className="font-medium text-foreground">{updated ? `Updated ${updated}.` : "Updated automatically."}</span> TimesFM
          runs on GitHub after each draw and this site is rebuilt from its results, so forecasts and backtests are ready when you
          open it; nothing is computed on request. Lines are sampled and saved in your browser. Source and the full local app:{" "}
          <a className="font-medium text-foreground underline underline-offset-2" href={REPO_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </p>
      </div>
    </aside>
  );
}
