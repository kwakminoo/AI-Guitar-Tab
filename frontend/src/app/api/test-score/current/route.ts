import { readFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";
import { TEST_SCORE_REL_SEGMENTS } from "@/lib/testScoreConfig";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function candidatePaths(): string[] {
  const cwd = process.cwd();
  const rel = [...TEST_SCORE_REL_SEGMENTS];
  return [
    path.join(cwd, "src", ...rel),
    path.join(cwd, "frontend", "src", ...rel),
  ];
}

export async function GET() {
  const fileName = TEST_SCORE_REL_SEGMENTS[TEST_SCORE_REL_SEGMENTS.length - 1];
  for (const filePath of candidatePaths()) {
    try {
      const text = await readFile(filePath, "utf-8");
      return new NextResponse(text, {
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
      });
    } catch {
      // try next path
    }
  }
  return NextResponse.json({ error: `${fileName} not found on server` }, { status: 404 });
}
