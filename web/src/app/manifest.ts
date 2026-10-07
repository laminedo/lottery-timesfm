import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Lottery Forecast Lab",
    short_name: "Forecast Lab",
    description: "Lottery draw analytics and experimental TimesFM forecasts. For analysis and entertainment only.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f9f9f7",
    theme_color: "#256abf",
    categories: ["entertainment", "utilities"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
