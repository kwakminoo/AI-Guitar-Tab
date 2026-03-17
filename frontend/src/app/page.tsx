"use client";

import { ScoreViewer, type AlphaTabScore } from "@/components/ScoreViewer";
import { useState, useTransition } from "react";

export default function Home() {
  const [url, setUrl] = useState("");
  const [score, setScore] = useState<AlphaTabScore | null>(null);
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState<string | null>(null);

  const handleAnalyze = () => {
    if (!url) return;
    setStatus("분석을 시작합니다...");
    startTransition(async () => {
      try {
        // TODO: 실제 FastAPI 파이프라인 엔드포인트로 교체
        // const res = await fetch("http://localhost:8000/api/score/from-youtube", { ... });
        // const json = await res.json();
        // setScore(json);
        // 임시 목업 데이터
        const mock: AlphaTabScore = {
          version: 1,
          meta: {
            title: "Demo Tab",
            tempo: 90,
            timeSignature: { numerator: 4, denominator: 4 },
            key: "Db major",
            capo: 1,
          },
          tracks: [
            {
              name: "Guitar",
              type: "guitar",
              strings: 6,
              tuning: [40, 45, 50, 55, 59, 64],
              beats: [
                {
                  time: 0,
                  chord: "Db",
                  lyric: "When I met you in the summer",
                  notes: [
                    { string: 4, fret: 6, start: 0, end: 0.5 },
                    { string: 3, fret: 6, start: 0.5, end: 1 },
                  ],
                },
              ],
            },
          ],
        };
        setScore(mock);
        setStatus("분석이 완료되었습니다.");
      } catch (e) {
        setStatus("분석 중 오류가 발생했습니다.");
      }
    });
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
              disabled={isPending || !url}
              className="w-full rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isPending ? "분석 중..." : "Analyze"}
            </button>
            {status && (
              <p className="mt-2 text-xs text-zinc-500">{status}</p>
            )}
            <div className="mt-4 border-t border-zinc-100 pt-3 text-xs text-zinc-500">
              분석이 완료되면 오른쪽에 타브 악보가 Songsterr처럼 표시됩니다.
            </div>
          </div>
        </section>

        <section className="flex min-h-[420px] flex-1">
          <ScoreViewer score={score} />
        </section>
      </main>
    </div>
  );
}

