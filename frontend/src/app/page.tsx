"use client";

import { ScoreViewer, type AlphaTabScore } from "@/components/ScoreViewer";
import { useState } from "react";

type SongMeta = {
  title: string;
  artist: string;
  lyrics: string | null;
  chords: string[];
  key?: string;
  capo?: number;
};

/** Next 리라이트로 동일 출처 `/api/*` 사용 (CORS 회피). 직접 백엔드 호출 시에만 절대 URL. */
function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";
  return base ? `${base}${path}` : path;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [score, setScore] = useState<AlphaTabScore | null>(null);
  const [scoreViewerKey, setScoreViewerKey] = useState(0);
  const [songMeta, setSongMeta] = useState<SongMeta | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAnalyze = async () => {
    if (!url.trim()) return;
    setScoreViewerKey((k) => k + 1);
    setStatus("오디오 다운로드 및 타브 분석 중… (최대 수분 걸릴 수 있음)");
    setErrorDetail(null);
    setScore(null);
    setSongMeta(null);
    setIsAnalyzing(true);

    try {
      const res = await fetch(apiUrl("/api/youtube/tab-preview"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });

      const payload = (await res.json().catch(() => ({}))) as {
        detail?: string;
        title?: string;
        artist?: string;
        lyrics?: string | null;
        score?: AlphaTabScore;
      };

      if (!res.ok) {
        const msg =
          typeof payload.detail === "string"
            ? payload.detail
            : `요청 실패 (${res.status})`;
        throw new Error(msg);
      }

      if (!payload.score || !payload.title) {
        throw new Error("서버 응답 형식이 올바르지 않습니다.");
      }

      setSongMeta({
        title: payload.title,
        artist: payload.artist ?? "Unknown Artist",
        lyrics: payload.lyrics ?? null,
        chords: payload.score.meta?.chords ?? [],
        key: payload.score.meta?.key,
        capo: payload.score.meta?.capo,
      });
      setScore(payload.score);
      setStatus("표시할 악보를 준비했습니다.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "요청 처리 중 오류가 발생했습니다.";
      setErrorDetail(message);
      setStatus(null);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="flex h-screen min-h-screen flex-col bg-zinc-100">
      <header className="z-20 shrink-0 border-b border-zinc-200 bg-white px-4 py-3 shadow-sm">
        <div className="mx-auto flex w-full max-w-[1800px] items-center justify-between gap-4">
          <div className="flex flex-col">
            <span className="text-lg font-semibold tracking-tight text-zinc-900">
              AI Guitar Tab
            </span>
            <span className="text-xs text-zinc-500">
              유튜브에서 앞부분 오디오를 받아 리듬·기타 전사 후 타브 악보로 표시합니다
            </span>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        <ScoreViewer
          key={scoreViewerKey}
          score={score}
          songTitle={songMeta?.title}
          songArtist={songMeta?.artist}
          songLyrics={songMeta?.lyrics}
          songChords={songMeta?.chords ?? []}
          youtubeUrl={url}
          onYoutubeUrlChange={setUrl}
          onAnalyze={handleAnalyze}
          isAnalyzing={isAnalyzing}
          statusMessage={status}
          analyzeError={errorDetail}
        />
      </main>
    </div>
  );
}
