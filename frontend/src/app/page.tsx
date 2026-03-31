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
          if (Number.isFinite(p)) setAnalyzeProgress(Math.max(0, Math.min(100, p)));
          if (progressPayload.detail) setStatus(progressPayload.detail);
          if (progressPayload.done) stopped = true;
        } catch {
          // progress polling 실패는 본 요청을 중단시키지 않는다.
        }
      };

      timer = window.setInterval(() => {
        if (stopped) return;
        void poll();
      }, 1000);
      await poll();

      const res = await fetch(apiUrl("/api/youtube/tab-preview"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), jobId }),
      });
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

  const handlePreviewMidi = async (file: File): Promise<{ ok: boolean; message?: string }> => {
    setStatus("MIDI 파일을 분석해 악보를 생성 중…");
    setErrorDetail(null);
    setIsAnalyzing(true);

    try {
      const formData = new FormData();
      formData.append("file", file, file.name);
      const res = await fetch(apiUrl("/api/midi/tab-preview"), {
        method: "POST",
        body: formData,
      });
      const payload = (await res.json().catch(() => ({}))) as {
        detail?: string;
        title?: string;
        score?: AlphaTabScore;
        alphatex?: string;
      };
      if (!res.ok) {
        const msg =
          typeof payload.detail === "string" ? payload.detail : `요청 실패 (${res.status})`;
        throw new Error(msg);
      }
      if (!payload.score) {
        throw new Error("서버 응답 형식이 올바르지 않습니다.");
      }

      const title = payload.title?.trim() || file.name.replace(/\.(mid|midi)$/i, "");
      setSongMeta({
        title,
        artist: "MIDI Preview",
        lyrics: null,
        chords: payload.score.meta?.chords ?? [],
        key: payload.score.meta?.key,
        capo: payload.score.meta?.capo,
      });
      setScore(payload.score);
      setAlphaTex(payload.alphatex ?? null);
      setScoreViewerKey((k) => k + 1);
      setStatus("MIDI 미리듣기용 악보를 불러왔습니다.");
      return { ok: true };
    } catch (e) {
      const message = e instanceof Error ? e.message : "MIDI 처리 중 오류가 발생했습니다.";
      setErrorDetail(message);
      setStatus(null);
      return { ok: false, message };
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
          alphaTex={alphaTex}
          songTitle={songMeta?.title}
          songArtist={songMeta?.artist}
          songLyrics={songMeta?.lyrics}
          songChords={songMeta?.chords ?? []}
          youtubeUrl={url}
          onYoutubeUrlChange={setUrl}
          onAnalyze={handleAnalyze}
          onPreviewMidi={handlePreviewMidi}
          isAnalyzing={isAnalyzing}
          statusMessage={status}
          analyzeError={errorDetail}
          analyzeProgress={analyzeProgress}
        />
      </main>
    </div>
  );
}
