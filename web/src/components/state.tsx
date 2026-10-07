import { CircleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { IS_STATIC } from "@/lib/env";

/** Shown when a request fails. Says what happened and what to do about it. */
export function ErrorNote({ error, action }: { error: Error; action?: string }) {
  const offline = !IS_STATIC && (error.message.includes("not reachable") || error.message === "Failed to fetch");
  return (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertTitle>{offline ? "The forecast API is not running" : "Something went wrong"}</AlertTitle>
      <AlertDescription>
        {offline
          ? "Start the backend (uvicorn app.main:app in the backend folder), then reload this page."
          : `${error.message}${action ? ` ${action}` : ""}`}
      </AlertDescription>
    </Alert>
  );
}

export function LoadingBlock({ className = "h-64" }: { className?: string }) {
  return <Skeleton className={`w-full ${className}`} />;
}
