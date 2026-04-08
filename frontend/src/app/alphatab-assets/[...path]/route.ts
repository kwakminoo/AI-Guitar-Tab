import { readFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const CONTENT_TYPES: Record<string, string> = {
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".sf2": "audio/sf2",
  ".json": "application/json; charset=utf-8",
};

function candidateBaseDirs(): string[] {
  const cwd = process.cwd();
  return [
    path.join(cwd, "node_modules", "@coderline", "alphatab", "dist"),
    path.join(cwd, "frontend", "node_modules", "@coderline", "alphatab", "dist"),
  ];
}

function isSafeAssetPath(parts: string[]): boolean {
  if (parts.length === 0) return false;
  if (parts.some((p) => p.includes("..") || p.includes("\\") || p.length === 0)) return false;
  const top = parts[0];
  return top === "font" || top === "soundfont" || (parts.length === 1 && parts[0] === "alphaTab.js");
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ path?: string[] }> },
) {
  const params = await context.params;
  const fileParts = params.path ?? [];
  if (!isSafeAssetPath(fileParts)) {
    return NextResponse.json({ error: "invalid alphaTab asset path" }, { status: 400 });
  }

  for (const baseDir of candidateBaseDirs()) {
    const fullPath = path.join(baseDir, ...fileParts);
    try {
      const bytes = await readFile(fullPath);
      const ext = path.extname(fullPath).toLowerCase();
      const contentType = CONTENT_TYPES[ext] ?? "application/octet-stream";
      return new NextResponse(bytes, {
        headers: {
          "Content-Type": contentType,
          "Cache-Control": "public, max-age=3600, immutable",
        },
      });
    } catch {
      // try next candidate
    }
  }

  return NextResponse.json({ error: "alphaTab asset not found" }, { status: 404 });
}
