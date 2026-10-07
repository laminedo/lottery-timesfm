"use client";

import { Archive } from "lucide-react";

import { useApi, type Health } from "@/lib/api";
import { IS_STATIC, REPO_URL } from "@/lib/env";
import { formatDate } from "@/lib/format";

/** Shown only in the read-only demo: says plainly that this copy is a snapshot, and of when. */
export function DemoNotice() {
  const { data } = useApi<Health>(IS_STATIC ? "/api/health" : null);
  if (!IS_STATIC) return null;
  return (
    <aside aria-label="About this demo" className="border-b bg-card">
      <div className="mx-auto flex w-full max-w-6xl items-start gap-2.5 px-4 py-2.5 text-xs leading-relaxed text-muted-foreground sm:px-6 sm:text-[0.8rem]">
        <Archive aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
        <p>
          <span className="font-medium text-foreground">
            Read-only demo{data?.exported_at ? `, snapshot of ${formatDate(data.exported_at)}` : ""}.
          </span>{" "}
          Forecasts and backtests were computed with TimesFM in advance; this copy does not run the model, fetch newer draws
          or save anything. Lines are sampled in your browser. The{" "}
          <a className="font-medium text-foreground underline underline-offset-2" href={REPO_URL} target="_blank" rel="noreferrer">
            full app
          </a>{" "}
          runs locally with live data.
        </p>
      </div>
    </aside>
  );
}
