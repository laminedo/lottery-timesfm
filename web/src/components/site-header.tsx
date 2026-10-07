"use client";

import { CloudOff, Cpu, LineChart } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useApi, type Health } from "@/lib/api";
import { IS_STATIC } from "@/lib/env";

/** Which model is producing the forecasts. Never implies TimesFM is running when it is not. */
function BackendBadge() {
  const { data, error } = useApi<Health>("/api/health", { refreshInterval: IS_STATIC ? 0 : 30_000 });
  if (IS_STATIC) {
    return (
      <Badge variant="secondary">
        <Cpu /> {data?.backend.name === "smoothing" ? "Smoothing" : "TimesFM 2.5"}
        {data?.exported_at
          ? ` · updated ${new Date(data.exported_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
          : ""}
      </Badge>
    );
  }
  if (error) {
    return (
      <Badge variant="destructive">
        <CloudOff /> API offline
      </Badge>
    );
  }
  if (!data) return null;
  const b = data.backend;
  const timesfm = b.name === "timesfm";
  const label = timesfm ? `TimesFM 2.5${b.ready ? ` · ${b.remote ? "remote" : b.device}` : ""}` : "Smoothing fallback";
  return (
    <Tooltip>
      <TooltipTrigger render={<Badge variant={timesfm ? "secondary" : "outline"} />}>
        <Cpu /> {label}
      </TooltipTrigger>
      <TooltipContent>
        {timesfm
          ? `Forecasts come from ${b.model ?? "TimesFM"}. ${b.ready ? "The model is loaded." : "Saved forecasts are being served; the model loads when a new one is needed."}`
          : "TimesFM is not installed on the server, so forecasts use exponential smoothing instead."}
      </TooltipContent>
    </Tooltip>
  );
}

export function SiteHeader() {
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <LineChart className="size-4" />
          </span>
          Lottery Forecast Lab
        </Link>
        <BackendBadge />
      </div>
    </header>
  );
}
