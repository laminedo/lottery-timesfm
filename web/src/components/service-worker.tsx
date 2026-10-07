"use client";

import { useEffect } from "react";

import { BASE_PATH } from "@/lib/env";

/** Registers the service worker in production builds, which makes the app installable and usable offline. */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(`${BASE_PATH}/sw.js`, { scope: `${BASE_PATH}/`, updateViaCache: "none" }).catch(() => {
      // Not installable in this browser or context; the app works the same without it.
    });
  }, []);
  return null;
}
