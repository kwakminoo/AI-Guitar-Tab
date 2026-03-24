"use client";

import { ScoreViewer, type AlphaTabScore } from "@/components/ScoreViewer";
import { useEffect, useRef, useState } from "react";

type SongMeta = {
  title: string;
  artist: string;
  lyrics: string | null;
  chords: string[];
  key?: string;
  capo?: number;
};

export default function Home() {
  const [url, setUrl] = useState("");
  const [score, setScore] = useState<AlphaTabScore | null>(null);
  const [songMeta, setSongMeta] = useState<SongMeta | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phaseText, setPhaseText] = useState<string>("");

  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  const handleAnalyze = () => {
    if (!url) return;
    setStatus("분석을 시작합니다...");
    setErrorDetail(null);
    setScore(null);
    setIsAnalyzing(true);
    setProgress(0);
    setPhaseText("메타/가사 준비 중...");

    eventSourceRef.current?.close();
    eventSourceRef.current = null;

    const streamUrl = `http://localhost:8000/api/score/from-youtube/stream?url=${encodeURIComponent(url)}`;
    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as {
          stage: "grid" | "notes" | "harmony" | "done" | "error";
          progress?: number;
          title?: string;
          artist?: string;
          lyrics?: string | null;
          detail?: string;
          score?: AlphaTabScore;
        };

        if (msg.stage === "grid") {
          setPhaseText("가사/마디 그리드 생성 중...");
          setProgress(msg.progress ?? 20);
          if (msg.title && msg.artist) {
            setSongMeta((prev) => ({
              title: msg.title!,
              artist: msg.artist!,
              lyrics: msg.lyrics ?? prev?.lyrics ?? null,
              chords: msg.score?.meta?.chords ?? prev?.chords ?? [],
              key: msg.score?.meta?.key,
              capo: msg.score?.meta?.capo,
            }));
          }
          if (msg.score) setScore(msg.score);
          return;
        }

        if (msg.stage === "notes") {
          setPhaseText("노트/프렛 전사 반영 중...");
          setProgress(msg.progress ?? 65);
          if (msg.score) setScore(msg.score);
          return;
        }

        if (msg.stage === "harmony") {
          setPhaseText("키/코드 마디 반영 중...");
          setProgress(msg.progress ?? 95);
          if (msg.score) setScore(msg.score);
          return;
        }

        if (msg.stage === "done") {
          setPhaseText("분석 완료");
          setProgress(msg.progress ?? 100);
          setStatus("분석이 완료되었습니다.");
          if (msg.score) setScore(msg.score);
          setIsAnalyzing(false);
          window.setTimeout(() => {
            setProgress(0);
            setPhaseText("");
          }, 700);
          es.close();
          eventSourceRef.current = null;
          return;
        }

        if (msg.stage === "error") {
          throw new Error(msg.detail ?? "오류가 발생했습니다.");
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : "오류 처리 중 예외가 발생했습니다.";
        setErrorDetail(message);
        setStatus("분석 중 오류가 발생했습니다.");
        setIsAnalyzing(false);
        setProgress(0);
        setPhaseText("");
        es.close();
        eventSourceRef.current = null;
      }
    };

    es.onerror = () => {
      setErrorDetail("스트림 연결이 실패했습니다.");
      setStatus("분석 중 오류가 발생했습니다.");
      setIsAnalyzing(false);
      setProgress(0);
      setPhaseText("");
      es.close();
      eventSourceRef.current = null;
    };
  };

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex flex-col">
            <span className="text-sm font-semibold tracking-tight text-zinc-900">
              AI Guitar Tab
            </span>
            <span className="text-xs text-zinc-500">
              유튜브 링크 하나로 기타 타브 악보 자동 생성
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-6 md:flex-row md:gap-6">
        <section className="w-full md:w-96">
          <div className="rounded-xl bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-zinc-900">
              1. 유튜브 링크 입력
            </h2>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              className="mb-3 w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:border-zinc-900 focus:outline-none"
            />
            <button
              onClick={handleAnalyze}
              disabled={isAnalyzing || !url}
              className="w-full rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isAnalyzing ? "분석 중..." : "Analyze"}
            </button>

            {isAnalyzing && (
              <div className="mt-3">
                <div className="h-2 w-full overflow-hidden rounded bg-zinc-200">
                  <div
                    className="h-full bg-zinc-900 transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] text-zinc-500">
                  {phaseText} ({progress}%)
                </p>
              </div>
            )}

            {status && (
              <div className="mt-2 flex flex-col gap-1">
                <p className="text-xs text-zinc-500">{status}</p>
                {errorDetail && (
                  <p className="text-xs text-red-600 break-words">
                    {errorDetail}
                  </p>
                )}
              </div>
            )}
            <div className="mt-4 border-t border-zinc-100 pt-3 text-xs text-zinc-500">
              분석이 완료되면 오른쪽에 타브 악보가 Songsterr처럼 표시됩니다.
            </div>
          </div>
        </section>

        <section className="flex min-h-[420px] flex-1">
          <ScoreViewer
            score={score}
            songTitle={songMeta?.title}
            songArtist={songMeta?.artist}
            songLyrics={songMeta?.lyrics}
            songChords={songMeta?.chords ?? []}
          />
        </section>
      </main>
    </div>
  );
}

