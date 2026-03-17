"use client";

import React, { useEffect, useRef, useState } from "react";

type AlphaTabNote = {
  string: number;
  fret: number;
  start: number;
  end: number;
};

type AlphaTabBeat = {
  time: number;
  chord: string | null;
  lyric: string | null;
  notes: AlphaTabNote[];
};

type AlphaTabTrack = {
  name: string;
  type: string;
  strings: number;
  tuning: number[];
  beats: AlphaTabBeat[];
};

export type AlphaTabScore = {
  version: number;
  meta: {
    title: string;
    tempo: number;
    timeSignature: { numerator: number; denominator: number };
    key: string;
    capo: number;
  };
  tracks: AlphaTabTrack[];
};

interface ScoreViewerProps {
  score: AlphaTabScore | null;
}

export const ScoreViewer: React.FC<ScoreViewerProps> = ({ score }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const apiRef = useRef<any>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    let disposed = false;
    if (!containerRef.current || !score) return;

    containerRef.current.innerHTML = "";

    (async () => {
      // Next.js(Turbopack) 환경에서 ESM 번들로 alphatab을 import하면 런타임 에러가 나는 케이스가 있어
      // UMD 번들을 CDN에서 로드해서 글로벌(alphaTab)로 사용한다.
      await loadAlphaTabUmd();
      if (disposed || !containerRef.current) return;

      const alphaTab = (window as any).alphaTab;
      if (!alphaTab) throw new Error("alphaTab UMD 로드에 실패했습니다.");

      const settings = new alphaTab.Settings();
      settings.display.renderTracks = [0];
      settings.display.resources = {
        colorBackground: 0xffffffff,
        colorScore: 0xff000000,
        colorTab: 0xff000000,
      };
      settings.display.layoutMode = alphaTab.LayoutMode.Page;
      settings.display.tempo = score.meta.tempo;

      const api = new alphaTab.AlphaTabApi(containerRef.current, settings);
      apiRef.current = api;

      const tex = buildAlphaTex(score);
      api.tex(tex);

      const onStateChanged = (e: any) => {
        setIsPlaying(String(e?.state).toLowerCase() === "playing");
      };
      api.player?.stateChanged?.on(onStateChanged);

      // cleanup handler stored on api instance
      (api as any).__cleanup = () => {
        api.player?.stateChanged?.off(onStateChanged);
        api.destroy?.();
      };
    })().catch(() => {
      // 렌더 실패 시 isPlaying만 초기화하고 화면은 그대로 둔다
      setIsPlaying(false);
    });

    return () => {
      disposed = true;
      if (apiRef.current?.__cleanup) apiRef.current.__cleanup();
      apiRef.current = null;
    };
  }, [score]);

  const handlePlayPause = () => {
    if (!apiRef.current) return;
    if (isPlaying) apiRef.current.player.pause();
    else apiRef.current.player.play();
  };

  if (!score) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-zinc-200 bg-white">
        <p className="text-sm text-zinc-500">
          분석이 완료되면 여기에서 타브 악보가 표시됩니다.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-xl border border-zinc-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2">
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-zinc-900">
            {score.meta.title}
          </span>
          <span className="text-xs text-zinc-500">
            Key: {score.meta.key} • Capo: {score.meta.capo} • ♩ ={" "}
            {score.meta.tempo}
          </span>
        </div>
        <button
          onClick={handlePlayPause}
          className="rounded-full border border-zinc-300 px-4 py-1 text-xs font-medium text-zinc-900 hover:bg-zinc-100"
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
      </div>
      <div
        ref={containerRef}
        className="flex-1 overflow-auto bg-white p-4"
      />
    </div>
  );
};

function convertToAlphaTabInternalFormat(score: AlphaTabScore): any {
  const track = score.tracks[0];
  return {
    score: {
      title: score.meta.title,
      tempo: score.meta.tempo,
      capo: score.meta.capo,
      tracks: [
        {
          name: track.name,
          tuning: track.tuning,
          bars: [
            {
              beats: track.beats.map((b) => ({
                start: b.time,
                chord: b.chord,
                lyric: b.lyric,
                notes: b.notes.map((n) => ({
                  string: n.string,
                  fret: n.fret,
                  start: n.start,
                  end: n.end,
                })),
              })),
            },
          ],
        },
      ],
    },
  };
}

function buildAlphaTex(score: AlphaTabScore): string {
  const t = score.tracks[0];
  const capo = score.meta.capo ?? 0;

  // AlphaTex에서 tuning은 (E4 B3 G3 D3 A2 E2) 같은 형태를 지원하지만
  // 여기서는 기본 EADGBE + capo만 세팅하고,
  // 노트는 "fret.string" 형태로 쭉 나열하는 최소 텍스트를 만든다.
  // (예: 3.1 은 1번줄 3프렛)

  const header = [
    `\\title "${escapeTex(score.meta.title)}"`,
    `\\tempo ${score.meta.tempo}`,
    `\\track "${escapeTex(t.name ?? "Guitar")}"`,
    `\\staff {tabs}`,
    capo > 0 ? `\\capo ${capo}` : "",
    "",
  ]
    .filter(Boolean)
    .join(" ");

  // beats -> 노트들을 순서대로 뽑아서 4/4 기준 8분음표(:8)로 쭉 표기
  const notes: string[] = [];
  for (const b of t.beats) {
    for (const n of b.notes) {
      // AlphaTex 표기: fret.string  (string: 1=highE)
      // ex) 3.1 , 0.2
      notes.push(`${n.fret}.${n.string}`);
    }
    // 박 경계 표시용으로 한 칸
    notes.push("");
  }

  const body = `:8 ${notes.join(" ").replace(/\s+/g, " ").trim()}`;
  return `${header} ${body}`.trim();
}

function escapeTex(input: string): string {
  return input.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

let alphatabUmdPromise: Promise<void> | null = null;
function loadAlphaTabUmd(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if ((window as any).alphaTab) return Promise.resolve();
  if (alphatabUmdPromise) return alphatabUmdPromise;

  alphatabUmdPromise = new Promise((resolve, reject) => {
    const id = "alphatab-umd";
    const existing = document.getElementById(id) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("alphaTab UMD load error")));
      return;
    }

    const script = document.createElement("script");
    script.id = id;
    script.async = true;
    script.src = "https://unpkg.com/@coderline/alphatab@1.8.1/dist/alphaTab.min.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("alphaTab UMD load error"));
    document.head.appendChild(script);
  });

  return alphatabUmdPromise;
}

