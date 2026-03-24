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
    chords?: string[];
  };
  tracks: AlphaTabTrack[];
};

type AlphaTabStateChanged = {
  on: (cb: (e: unknown) => void) => void;
  off: (cb: (e: unknown) => void) => void;
};

type AlphaTabPlayer = {
  pause: () => void;
  play: () => void;
  stateChanged?: AlphaTabStateChanged;
};

type AlphaTabApiHandle = {
  tex: (tex: string) => void;
  player?: AlphaTabPlayer;
  destroy?: () => void;
  __cleanup?: () => void;
};

type AlphaTabUmd = {
  Settings: new () => {
    display: {
      renderTracks: number[];
      resources: { colorBackground: number; colorScore: number; colorTab: number };
      layoutMode: unknown;
      padding: number[];
      tempo: number;
    };
  };
  LayoutMode: { Page: unknown };
  AlphaTabApi: new (container: HTMLDivElement, settings: unknown) => AlphaTabApiHandle;
};

/** 유튜브 링크 없이 초기 로드 시 표시할 빈 악보(오선보+타브, 4마디 휴지) */
const EMPTY_ALPHATEX = [
  '\\title "빈 악보"',
  "\\tempo 90",
  "\\ts (4 4)",
  '\\track "Guitar"',
  "\\staff {tabs}",
  ":4 r r r r | :4 r r r r | :4 r r r r | :4 r r r r |",
].join(" ");

interface ScoreViewerProps {
  score: AlphaTabScore | null;
  songTitle?: string | null;
  songArtist?: string | null;
  songLyrics?: string | null;
  songChords?: string[];
}

export const ScoreViewer: React.FC<ScoreViewerProps> = ({
  score,
  songTitle,
  songArtist,
}) => {
  const alphaTabContainerRef = useRef<HTMLDivElement | null>(null);
  const apiRef = useRef<AlphaTabApiHandle | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    if (!alphaTabContainerRef.current) return;

    let disposed = false;
    alphaTabContainerRef.current.innerHTML = "";

    // 빈 상태(score === null)에서는 alphaTab 렌더를 돌리지 않음.
    // 현재 EMPTY/오선 렌더 경로에서 TypeError가 발생해 UI까지 죽는 문제가 있음.
    if (!score) {
      setRenderError(null);
      setIsPlaying(false);
      if (apiRef.current?.__cleanup) apiRef.current.__cleanup();
      apiRef.current = null;
      return;
    }

    const normalized = score ? normalizeScoreForRendering(score) : null;
    if (score && !normalized) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRenderError("악보 데이터 형식이 올바르지 않습니다.");
      return;
    }

    const tex = score && normalized ? buildAlphaTex(normalized) : EMPTY_ALPHATEX;
    const tempo = normalized?.meta.tempo ?? score?.meta?.tempo ?? 90;

    (async () => {
      await loadAlphaTabUmd();
      if (disposed || !alphaTabContainerRef.current) return;

      const alphaTab = (window as unknown as { alphaTab?: AlphaTabUmd }).alphaTab;
      if (!alphaTab) throw new Error("alphaTab UMD 로드에 실패했습니다.");

      const settings = new alphaTab.Settings();
      settings.display.renderTracks = [0];
      settings.display.resources = {
        // 아래에 있는 빈 악보 가이드를 유지하기 위해 배경을 투명하게 둔다.
        colorBackground: 0x00000000,
        colorScore: 0xff000000,
        colorTab: 0xff000000,
      };
      settings.display.layoutMode = alphaTab.LayoutMode.Page;
      // 컨테이너 상단 여백을 줄여서(제목 아래 영역에) 더 위에 렌더되게 한다.
      settings.display.padding = [10, 0];
      settings.display.tempo = tempo;

      const api = new alphaTab.AlphaTabApi(alphaTabContainerRef.current, settings);
      apiRef.current = api;

      // 레이아웃이 아직 계산되기 전일 수 있어, 다음 프레임에 렌더
      requestAnimationFrame(() => {
        try {
          setRenderError(null);
          api.tex(tex);
        } catch (e) {
          const msg = e instanceof Error ? e.message : "AlphaTab 렌더 실패";
          setRenderError(msg);
          // 콘솔로도 남겨서 원인 파악이 가능하게 한다
          console.error(e);
        }
      });

      const onStateChanged = (e: unknown) => {
        const state = (e as { state?: unknown } | undefined)?.state;
        setIsPlaying(String(state).toLowerCase() === "playing");
      };
      api.player?.stateChanged?.on(onStateChanged);

      api.__cleanup = () => {
        api.player?.stateChanged?.off(onStateChanged);
        api.destroy?.();
      };
    })().catch((e) => {
      const msg = e instanceof Error ? e.message : "AlphaTab 초기화 실패";
      setRenderError(msg);
      setIsPlaying(false);
      console.error(e);
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

  const titleText = score?.meta.title || songTitle || "빈 악보";
  const artistText = songArtist || "";
  const canPlay = Boolean(
    score?.tracks?.some((tr) => tr.beats.some((b) => Array.isArray(b.notes) && b.notes.length > 0)),
  );

  return (
    <div className="flex h-full flex-col rounded-xl border border-zinc-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2">
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-zinc-900">
            {score ? "악보" : "빈 악보"}
          </span>
          <span className="text-xs text-zinc-500">
            {score
              ? `Key: ${score.meta.key} • Capo: ${score.meta.capo} • ♩ = ${score.meta.tempo}`
              : "Analyze를 누르면 이 페이지 위에 악보가 작성됩니다."}
          </span>
        </div>
        {score && canPlay && (
          <button
            onClick={handlePlayPause}
            className="rounded-full border border-zinc-300 px-4 py-1 text-xs font-medium text-zinc-900 hover:bg-zinc-100"
          >
            {isPlaying ? "Pause" : "Play"}
          </button>
        )}
      </div>

      <div className="flex-1 overflow-auto bg-zinc-50 p-6">
        <div className="mx-auto w-full max-w-[860px] aspect-[210/297] rounded-md border border-zinc-200 bg-white shadow-md">
          <div className="flex h-full w-full flex-col">
            {/* 타이틀 영역(빈 악보 포맷 유지) */}
            <div
              className="shrink-0"
              style={{ height: `${(44 / 297) * 100}%` }}
            >
              <svg viewBox="0 0 210 44" className="h-full w-full text-zinc-400">
                <text
                  x="105"
                  y="22"
                  textAnchor="middle"
                  fontSize="10"
                  fill="currentColor"
                >
                  {titleText}
                </text>
                {artistText && (
                  <text
                    x="105"
                    y="34"
                    textAnchor="middle"
                    fontSize="6"
                    fill="currentColor"
                    opacity="0.85"
                  >
                    {artistText}
                  </text>
                )}
                <line
                  x1="35"
                  y1="30"
                  x2="175"
                  y2="30"
                  stroke="currentColor"
                  strokeWidth="0.5"
                />
              </svg>
            </div>

            {/* 하단: 빈 악보 가이드(항상) + 분석 시 alphaTab 렌더 오버레이 */}
            <div className="relative flex-1 overflow-hidden">
              <svg viewBox="0 44 210 253" className="h-full w-full text-zinc-400">
                {/* 시스템(오선+TAB) 여러 줄로 페이지 채우기 */}
                {Array.from({ length: 5 }).map((_, idx) => {
                  const top = 44 + idx * 50;
                  const staffGap = 2.3;
                  const tabTop = top + 16;
                  const left = 18;
                  const right = 192;

                  return (
                    <g key={`sys-${idx}`}>
                      {/* 오선보 5줄 */}
                      {[0, 1, 2, 3, 4].map((i) => (
                        <line
                          key={`staff-${idx}-${i}`}
                          x1={left}
                          y1={top + i * staffGap}
                          x2={right}
                          y2={top + i * staffGap}
                          stroke="currentColor"
                          strokeWidth="0.45"
                        />
                      ))}

                      {/* 타브 6줄 */}
                      {[0, 1, 2, 3, 4, 5].map((i) => (
                        <line
                          key={`tab-${idx}-${i}`}
                          x1={left}
                          y1={tabTop + i * staffGap}
                          x2={right}
                          y2={tabTop + i * staffGap}
                          stroke="currentColor"
                          strokeWidth="0.45"
                        />
                      ))}

                      {/* TAB 레이블 */}
                      <text x="10" y={tabTop + 3} fontSize="5.2" fill="currentColor">
                        T
                      </text>
                      <text x="10" y={tabTop + 3 + staffGap} fontSize="5.2" fill="currentColor">
                        A
                      </text>
                      <text
                        x="10"
                        y={tabTop + 3 + staffGap * 2}
                        fontSize="5.2"
                        fill="currentColor"
                      >
                        B
                      </text>

                      {/* 마디 구분선(대충) */}
                      {[0, 1, 2, 3].map((b) => (
                        <line
                          key={`bar-${idx}-${b}`}
                          x1={left + (right - left) * ((b + 1) / 4)}
                          y1={top - 1}
                          x2={left + (right - left) * ((b + 1) / 4)}
                          y2={tabTop + staffGap * 5 + 1}
                          stroke="currentColor"
                          strokeWidth="0.35"
                          opacity="0.8"
                        />
                      ))}
                    </g>
                  );
                })}

                {/* 페이지 하단 가이드 */}
                <text
                  x="105"
                  y="288"
                  textAnchor="middle"
                  fontSize="4.5"
                  fill="currentColor"
                  opacity="0.9"
                >
                  Analyze를 누르면 이 페이지 위에 악보가 렌더링됩니다.
                </text>
              </svg>

              {score && (
                <>
                  {renderError && (
                    <div className="absolute left-4 top-4 z-10 rounded-md bg-white/90 px-3 py-2 text-xs text-red-700 shadow-sm">
                      악보 렌더링 오류: {renderError}
                    </div>
                  )}
                  <div ref={alphaTabContainerRef} className="absolute inset-0 h-full w-full" />
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

function buildAlphaTex(score: AlphaTabScore): string {
  const t = score.tracks[0];
  const capo = score.meta.capo ?? 0;
  const ts = score.meta.timeSignature;
  const num = ts?.numerator ?? 4;
  const den = ts?.denominator ?? 4;

  // (안정화) AlphaTab 파서 에러를 피하기 위해 body를 "마디(|) 단위"로 고정 길이 beat을 나열한다.
  // 제목은 UI 타이틀 영역에서만 표시하므로 AlphaTab tex에서는 제외한다.
  const header = [
    `\\tempo ${score.meta.tempo}`,
    `\\ts (${num} ${den})`,
    `\\track "${escapeTex(t.name ?? "Guitar")}"`,
    "\\staff {tabs}",
    capo > 0 ? `\\capo ${capo}` : "",
    "",
  ]
    .filter(Boolean)
    .join(" ");

  // beats -> notes를 beat 단위로 순서대로 나열한다.
  // - no note: rest 'r'
  // - 1 note: fret.string
  // - multi note: (fret.string fret.string ...)
  const beatTokens: string[] = [];
  for (const b of t.beats) {
    const chordText = b.chord?.trim() || null;
    const lyricText = b.lyric?.trim() || null;
    const beatText = chordText && lyricText ? `${chordText} ${lyricText}` : chordText || lyricText;

    if (!b.notes || b.notes.length === 0) {
      if (beatText) beatTokens.push(`0.1{hide txt "${escapeTex(beatText)}"}`);
      else beatTokens.push("r");
      continue;
    }
    if (b.notes.length === 1) {
      const n = b.notes[0];
      const token = `${n.fret}.${n.string}`;
      if (beatText) beatTokens.push(`${token}{txt "${escapeTex(beatText)}"}`);
      else beatTokens.push(token);
      continue;
    }
    const tokens = b.notes.map((n) => `${n.fret}.${n.string}`);
    if (beatText) tokens[0] = `${tokens[0]}{txt "${escapeTex(beatText)}"}`;
    beatTokens.push(`(${tokens.join(" ")})`);
  }

  const durationDen = [1, 2, 4, 8, 16].includes(den) ? den : 4;
  const beatsPerBar = Math.max(1, num);
  const barCount = Math.max(1, Math.ceil(beatTokens.length / beatsPerBar));

  const barStrings: string[] = [];
  for (let barIdx = 0; barIdx < barCount; barIdx++) {
    const start = barIdx * beatsPerBar;
    const end = start + beatsPerBar;
    const barTokens = beatTokens.slice(start, end);
    while (barTokens.length < beatsPerBar) barTokens.push("r"); // 마지막 마디 길이 고정
    barStrings.push(`:${durationDen} ${barTokens.join(" ")} |`);
  }

  const body = barStrings.join(" ").replace(/\s+/g, " ").trim();
  return `${header} ${body}`.trim();
}

function escapeTex(input: string): string {
  return input.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function normalizeScoreForRendering(score: AlphaTabScore): AlphaTabScore | null {
  if (!score?.meta || !Array.isArray(score.tracks) || score.tracks.length === 0) return null;
  const track0 = score.tracks[0];
  if (!track0 || !Array.isArray(track0.beats)) return null;

  const beats = track0.beats
    .map((b) => {
      const notes = Array.isArray(b?.notes)
        ? b.notes
            .map((n) => {
              const string = Number(n?.string);
              const fret = Number(n?.fret);
              const start = Number(n?.start ?? 0);
              const end = Number(n?.end ?? start + 0.25);
              if (!Number.isFinite(string) || !Number.isFinite(fret)) return null;
              return {
                string: Math.max(1, Math.min(6, Math.round(string))),
                fret: Math.max(0, Math.min(24, Math.round(fret))),
                start: Number.isFinite(start) ? start : 0,
                end: Number.isFinite(end) ? end : 0.25,
              };
            })
            .filter((n): n is AlphaTabNote => n !== null)
        : [];

      return {
        time: Number.isFinite(Number(b?.time)) ? Number(b?.time) : 0,
        chord: b?.chord ?? null,
        lyric: b?.lyric ?? null,
        notes,
      } satisfies AlphaTabBeat;
    })
    ;

  if (beats.length === 0) {
    beats.push({
      time: 0,
      chord: null,
      lyric: null,
      notes: [{ string: 6, fret: 0, start: 0, end: 0.5 }],
    });
  }

  return {
    ...score,
    meta: {
      ...score.meta,
      title: score.meta.title || "From YouTube",
      tempo: Number.isFinite(Number(score.meta.tempo)) ? Number(score.meta.tempo) : 90,
      timeSignature: {
        numerator: Number.isFinite(Number(score.meta.timeSignature?.numerator))
          ? Number(score.meta.timeSignature.numerator)
          : 4,
        denominator: Number.isFinite(Number(score.meta.timeSignature?.denominator))
          ? Number(score.meta.timeSignature.denominator)
          : 4,
      },
      key: score.meta.key || "C major",
      capo: Number.isFinite(Number(score.meta.capo)) ? Number(score.meta.capo) : 0,
    },
    tracks: [
      {
        ...track0,
        name: track0.name || "Guitar",
        type: track0.type || "guitar",
        strings: 6,
        tuning: [40, 45, 50, 55, 59, 64],
        beats,
      },
    ],
  };
}

let alphatabUmdPromise: Promise<void> | null = null;
function loadAlphaTabUmd(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  const alphaTabMaybe = (window as unknown as { alphaTab?: AlphaTabUmd }).alphaTab;
  if (alphaTabMaybe) return Promise.resolve();
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

