"use client";

import { ScoreViewer, type AlphaTabScore } from "@/components/ScoreViewer";
import { useRef, useState } from "react";

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
  const envBase = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";
  if (envBase) return `${envBase}${path}`;

  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    // 로컬 개발에서는 Next 프록시(ECONNRESET) 우회: 백엔드로 직접 호출
    if (host === "localhost" || host === "127.0.0.1") {
      return `http://127.0.0.1:8000${path}`;
    }
  }
  return path;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [score, setScore] = useState<AlphaTabScore | null>(null);
  const [alphaTex, setAlphaTex] = useState<string | null>(null);
  const [scoreViewerKey, setScoreViewerKey] = useState(0);
  const [songMeta, setSongMeta] = useState<SongMeta | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<number | null>(null);
  /** 백엔드 진행 스냅샷이 바뀔 때만 UI 갱신(불필요한 리렌더·로딩바 깜빡임 방지) */
  const lastProgressSnapshotRef = useRef<string>("");

  const handleAnalyze = async () => {
    if (!url.trim()) return;
    const jobId = `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    let stopped = false;
    let timer: number | null = null;
    setScoreViewerKey((k) => k + 1);
    setStatus("오디오 다운로드 및 타브 분석 중… (최대 수분 걸릴 수 있음)");
    setErrorDetail(null);
    setScore(null);
    setAlphaTex(null);
    setSongMeta(null);
    setIsAnalyzing(true);
    setAnalyzeProgress(0);
    lastProgressSnapshotRef.current = "";

    try {
      const poll = async () => {
        try {
          const progressRes = await fetch(apiUrl(`/api/youtube/tab-preview/progress/${jobId}`));
          const progressPayload = (await progressRes.json().catch(() => ({}))) as {
            progress?: number;
            stage?: string;
            detail?: string;
            done?: boolean;
          };
          const p = Number(progressPayload.progress ?? 0);
          const detail = typeof progressPayload.detail === "string" ? progressPayload.detail : "";
          const stage = typeof progressPayload.stage === "string" ? progressPayload.stage : "";
          const snapshot = `${p}|${stage}|${detail}|${Boolean(progressPayload.done)}`;
          if (snapshot !== lastProgressSnapshotRef.current) {
            lastProgressSnapshotRef.current = snapshot;
            if (Number.isFinite(p)) setAnalyzeProgress(Math.max(0, Math.min(100, p)));
            if (detail) setStatus(detail);
          }
          if (progressPayload.done) stopped = true;
        } catch {
          // progress polling 실패는 본 요청을 중단시키지 않는다.
        }
      };

      // POST가 오래 걸리므로 먼저 요청을 시작한 뒤, 같은 jobId로 진행률을 폴링해야 한다.
      const postPromise = fetch(apiUrl("/api/youtube/tab-preview"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          jobId,
        }),
      });

      timer = window.setInterval(() => {
        if (stopped) return;
        void poll();
      }, 700);
      void poll();

      const res = await postPromise;
      stopped = true;

      const payload = (await res.json().catch(() => ({}))) as {
        detail?: string;
        title?: string;
        artist?: string;
        lyrics?: string | null;
        score?: AlphaTabScore;
        alphatex?: string;
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
        artist: payload.artist ?? "",
        lyrics: payload.lyrics ?? null,
        chords: payload.score.meta?.chords ?? [],
        key: payload.score.meta?.key,
        capo: payload.score.meta?.capo,
      });
      setScore(payload.score);
      setAlphaTex(payload.alphatex ?? null);
      setStatus("표시할 악보를 준비했습니다.");
      setAnalyzeProgress(100);
    } catch (e) {
      const message = e instanceof Error ? e.message : "요청 처리 중 오류가 발생했습니다.";
      setErrorDetail(message);
      setStatus(null);
      setAnalyzeProgress(null);
      setAlphaTex(null);
    } finally {
      stopped = true;
      if (timer !== null) {
        window.clearInterval(timer);
      }
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
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        <ScoreViewer
          key={scoreViewerKey}
          score={score}
          alphaTex={alphaTex}
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
          analyzeProgress={analyzeProgress}
        />
      </main>
    </div>
  );
}
