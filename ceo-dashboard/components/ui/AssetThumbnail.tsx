"use client";

import { useEffect, useState } from "react";
import { fetchAssetBlobUrl } from "@/lib/api";

interface AssetThumbnailProps {
  // image_brief.image_path as stored, e.g. "assets_library/my_originals/foo.png"
  imagePath: string;
  alt: string;
  // Pixel size (square) — 64 for the list row, larger (e.g. 320) for the
  // per-post review expansion where the actual diagram needs to be legible.
  size?: number;
}

// Renders one assets_library/my_originals/ image via app/api/asset/[...path]/
// route.ts (this app's own route handler, cookie-session auth is
// automatic — no Bearer token needed, unlike the old FastAPI-backed
// version). Fetches the bytes once, renders as a blob URL, and revokes
// it on unmount/path change so object URLs don't leak across re-renders.
export function AssetThumbnail({ imagePath, alt, size = 64 }: AssetThumbnailProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let currentUrl: string | null = null;

    async function load() {
      try {
        const relativePath = imagePath.replace(/^assets_library\//, "");
        const url = await fetchAssetBlobUrl(relativePath);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        currentUrl = url;
        setBlobUrl(url);
      } catch {
        if (!cancelled) setError(true);
      }
    }
    load();

    return () => {
      cancelled = true;
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [imagePath]);

  if (error) {
    return <span className="text-[10.5px] font-mono" style={{ color: "#e05d5d" }}>image failed to load</span>;
  }
  if (!blobUrl) {
    return (
      <div
        className="rounded-[6px] shrink-0"
        style={{ width: size, height: size, backgroundColor: "#10151b", border: "1px solid #1c222b" }}
      />
    );
  }

  // eslint-disable-next-line @next/next/no-img-element -- blob: URL, next/image can't optimize it
  return (
    <img
      src={blobUrl}
      alt={alt}
      className="rounded-[6px] object-cover shrink-0"
      style={{ width: size, height: size, border: "1px solid #1c222b" }}
    />
  );
}
