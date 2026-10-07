import type { Metadata, Viewport } from "next";

import { DemoNotice } from "@/components/demo-notice";
import { ServiceWorker } from "@/components/service-worker";
import { Disclaimer, SiteFooter } from "@/components/site-chrome";
import { SiteHeader } from "@/components/site-header";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BASE_PATH } from "@/lib/env";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Lottery Forecast Lab", template: "%s · Lottery Forecast Lab" },
  description:
    "Statistical pattern analysis and experimental TimesFM time-series forecasts for Powerball, Mega Millions, Hit 5 and Lotto. For analysis and entertainment only.",
  applicationName: "Lottery Forecast Lab",
  manifest: `${BASE_PATH}/manifest.webmanifest`,
  appleWebApp: { capable: true, title: "Forecast Lab", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f9f9f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0d0d" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <TooltipProvider>
          <SiteHeader />
          <Disclaimer />
          <DemoNotice />
          <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-4 py-4 sm:px-6">{children}</main>
          <SiteFooter />
        </TooltipProvider>
        <ServiceWorker />
      </body>
    </html>
  );
}
