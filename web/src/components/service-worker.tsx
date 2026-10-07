"use client";

import { useEffect } from "react";

/** Registers the service worker in production builds, which makes the app installable and usable offline. */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {
      // Not installable in this browser or context; the app works the same without it.
    });
  }, []);
  return null;
}
