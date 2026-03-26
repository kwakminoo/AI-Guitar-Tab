"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { AlphaTabBeat, AlphaTabNote, AlphaTabScore } from "@/types/alphatabScore";
import { createEmptyEditableScore } from "@/lib/emptyAlphatabScore";

export type { AlphaTabScore } from "@/types/alphatabScore";

function IconPlay({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7-11-7z" />
    </svg>
  );
}

function IconPause({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
    </svg>
  );
}

function IconHourglass({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M8 2h8v4l-4 4-4-4V2zM8 22h8v-4l-4-4-4 4v4z" strokeLinejoin="round" />
      <path d="M12 10v4" strokeLinecap="round" />
    </svg>
  );
}

function IconMetronome({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M12 3v2M9 21h6M10 7l-3 12h10l-3-12" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 7h4" strokeLinecap="round" />
    </svg>
  );
}

function IconLoop({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path
        d="M17 1l4 4-4 4M21 5H9a4 4 0 0 0-4 4v1M7 23l-4-4 4-4M3 19h12a4 4 0 0 0 4-4v-1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconPrint({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6v-8z" strokeLinejoin="round" />
    </svg>
  );
}

type AlphaTabModuleLike = {
  Settings: new () => {
    display: {
      layoutMode: unknown;
      scale: number;
      padding: number[];
    };
    player: {
      enablePlayer: boolean;
      soundFont: string;
      scrollElement?: HTMLElement;
    };
  };
  LayoutMode: {
    Horizontal: unknown;
    Page: unknown;
  };
  synth: {
    PlayerState: {
      Playing: unknown;
    };
  };
  AlphaTabApi: new (container: HTMLElement, settings: unknown) => AlphaTabApiLike;
};

type AlphaTabApiLike = {
  settings: {
    display: {
      layoutMode: unknown;
      scale: number;
    };
  };
  tracks: Array<{ index: number }>;
  countInVolume: number;
  metronomeVolume: number;
  isLooping: boolean;
  scoreLoaded: {
    on: (cb: (score: { tracks: Array<{ index: number; name: string }> }) => void) => void;
  };
  renderStarted: { on: (cb: () => void) => void };
  renderFinished: { on: (cb: () => void) => void };
  soundFontLoad: { on: (cb: (e: { loaded: number; total: number }) => void) => void };
  playerReady: { on: (cb: () => void) => void };
  playerStateChanged: { on: (cb: (e: { state: unknown }) => void) => void };
  playerPositionChanged: {
    on: (cb: (e: { currentTime: number; endTime: number }) => void) => void;
  };
  renderTracks: (tracks: unknown[]) => void;
  updateSettings: () => void;
  render: () => void;
  tex: (tex: string) => void;
  print: () => void;
  playPause: () => void;
  stop: () => void;
  destroy: () => void;
};

interface ScoreViewerProps {
  score: AlphaTabScore | null;
  songTitle?: string | null;
  songArtist?: string | null;
  songLyrics?: string | null;
  songChords?: string[];
  /** 사이드바: 유튜브 URL + 불러오기 */
  youtubeUrl?: string;
  onYoutubeUrlChange?: (value: string) => void;
  onAnalyze?: () => void;
  isAnalyzing?: boolean;
  statusMessage?: string | null;
  analyzeError?: string | null;
}

export const ScoreViewer: React.FC<ScoreViewerProps> = ({
  score,
  songTitle,
  songArtist,
  youtubeUrl = "",
  onYoutubeUrlChange,
  onAnalyze,
  isAnalyzing = false,
  statusMessage,
  analyzeError,
}) => {
  const mainRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const trackListRef = useRef<HTMLDivElement | null>(null);
  const apiRef = useRef<AlphaTabApiLike | null>(null);
  const alphaTabModuleRef = useRef<AlphaTabModuleLike | null>(null);
  const [nullBaseline] = useState<AlphaTabScore>(() => createEmptyEditableScore());
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isPlayerReady, setIsPlayerReady] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [songPosition, setSongPosition] = useState("00:00 / 00:00");
  const [playerProgress, setPlayerProgress] = useState("0%");
  const [isCountIn, setIsCountIn] = useState(false);
  const [isMetronome, setIsMetronome] = useState(false);
  const [isLooping, setIsLooping] = useState(false);
  const [zoom, setZoom] = useState("100");
  const [layout, setLayout] = useState<"page" | "horizontal">("page");
  const previousSecondRef = useRef(-1);

  const workingScore = score ?? nullBaseline;

  const normalizedScore = useMemo(
    () => normalizeScoreForRendering(workingScore),
    [workingScore],
  );
  const modelError =
    normalizedScore === null ? "악보 데이터 형식이 올바르지 않습니다." : null;

  useEffect(() => {
    if (!mainRef.current) return;

    let disposed = false;
    mainRef.current.innerHTML = "";
    trackListRef.current?.replaceChildren();
    previousSecondRef.current = -1;

    if (!normalizedScore) return;

    const tex = buildAlphaTex(normalizedScore);

    (async () => {
      const alphaTab = await loadAlphaTabUmd();
      if (disposed || !mainRef.current) return;
      alphaTabModuleRef.current = alphaTab;

      const settings = new alphaTab.Settings();
      settings.display.layoutMode =
        layout === "horizontal" ? alphaTab.LayoutMode.Horizontal : alphaTab.LayoutMode.Page;
      settings.display.scale = Number.parseInt(zoom, 10) / 100;
      settings.display.padding = [10, 10, 10, 10];
      settings.player.enablePlayer = true;
      settings.player.soundFont =
        "https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2";
      if (viewportRef.current) {
        settings.player.scrollElement = viewportRef.current;
      }

      const api = new alphaTab.AlphaTabApi(mainRef.current, settings);
      apiRef.current = api;

      const createTrackItem = (track: { index: number; name: string }) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className =
          "w-full rounded-md px-3 py-2 text-left text-xs font-medium text-zinc-600 transition hover:bg-zinc-200/70";
        item.textContent = track.name || `Track ${track.index + 1}`;
        item.onclick = () => {
          api.renderTracks([track as never]);
        };
        item.dataset.trackIndex = String(track.index);
        return item;
      };

      const markActiveTracks = () => {
        const list = trackListRef.current;
        if (!list) return;
        const activeIndices = new Set<number>();
        api.tracks.forEach((t) => activeIndices.add(t.index));
        list.querySelectorAll<HTMLButtonElement>("button[data-track-index]").forEach((btn) => {
          const idx = Number.parseInt(btn.dataset.trackIndex ?? "-1", 10);
          const active = activeIndices.has(idx);
          btn.className = active
            ? "w-full rounded-md bg-zinc-900 px-3 py-2 text-left text-xs font-semibold text-white"
            : "w-full rounded-md px-3 py-2 text-left text-xs font-medium text-zinc-600 transition hover:bg-zinc-200/70";
        });
      };

      const formatDuration = (milliseconds: number) => {
        let seconds = milliseconds / 1000;
        const minutes = (seconds / 60) | 0;
        seconds = (seconds - minutes * 60) | 0;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
      };

      api.scoreLoaded.on((loadedScore) => {
        const list = trackListRef.current;
        if (!list) return;
        list.replaceChildren();
        loadedScore.tracks.forEach((track) => {
          list.appendChild(createTrackItem(track as never));
        });
        markActiveTracks();
      });

      api.renderStarted.on(() => {
        if (overlayRef.current) overlayRef.current.style.display = "flex";
        markActiveTracks();
      });

      api.renderFinished.on(() => {
        if (overlayRef.current) overlayRef.current.style.display = "none";
      });

      api.soundFontLoad.on((e) => {
        const percentage = Math.floor((e.loaded / e.total) * 100);
        setPlayerProgress(`${percentage}%`);
      });

      api.playerReady.on(() => {
        setIsPlayerReady(true);
      });

      api.playerStateChanged.on((e) => {
        setIsPlaying(e.state === alphaTab.synth.PlayerState.Playing);
      });

      api.playerPositionChanged.on((e) => {
        const currentSeconds = (e.currentTime / 1000) | 0;
        if (currentSeconds === previousSecondRef.current) return;
        previousSecondRef.current = currentSeconds;
        setSongPosition(`${formatDuration(e.currentTime)} / ${formatDuration(e.endTime)}`);
      });

      requestAnimationFrame(() => {
        try {
          setRenderError(null);
          api.tex(tex);
        } catch (e) {
          const msg = e instanceof Error ? e.message : "AlphaTab 렌더 실패";
          setRenderError(msg);
          console.error(e);
        }
      });
    })().catch((e) => {
      const msg = e instanceof Error ? e.message : "AlphaTab 초기화 실패";
      setRenderError(msg);
      setIsPlaying(false);
      console.error(e);
    });

    return () => {
      disposed = true;
      apiRef.current?.destroy();
      apiRef.current = null;
    };
  }, [layout, normalizedScore, zoom]);

  const handlePlayPause = () => {
    if (!isPlayerReady) return;
    apiRef.current?.playPause();
  };

  const handleCountIn = () => {
    const next = !isCountIn;
    setIsCountIn(next);
    if (apiRef.current) apiRef.current.countInVolume = next ? 1 : 0;
  };

  const handleMetronome = () => {
    const next = !isMetronome;
    setIsMetronome(next);
    if (apiRef.current) apiRef.current.metronomeVolume = next ? 1 : 0;
  };

  const handleLoop = () => {
    const next = !isLooping;
    setIsLooping(next);
    if (apiRef.current) apiRef.current.isLooping = next;
  };

  const handlePrint = () => {
    apiRef.current?.print();
  };

  const handleZoomChange = (value: string) => {
    setZoom(value);
    const api = apiRef.current;
    if (!api) return;
    api.settings.display.scale = Number.parseInt(value, 10) / 100;
    api.updateSettings();
    api.render();
  };

  const handleLayoutChange = (value: "page" | "horizontal") => {
    setLayout(value);
    const api = apiRef.current;
    const alphaTab = alphaTabModuleRef.current;
    if (!alphaTab) return;
    if (!api) return;
    api.settings.display.layoutMode =
      value === "horizontal"
        ? alphaTab.LayoutMode.Horizontal
        : alphaTab.LayoutMode.Page;
    api.updateSettings();
    api.render();
  };

  const titleText = workingScore.meta.title || songTitle || "빈 악보";
  const artistText = songArtist || "Unknown Artist / Original";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <div className="relative flex min-h-0 flex-1 overflow-hidden bg-zinc-100">
        <aside className="z-10 flex h-full min-h-0 w-[19.5rem] shrink-0 flex-col overflow-hidden border-r border-zinc-200 bg-zinc-50">
          <div className="shrink-0 space-y-2 border-b border-zinc-200 p-3">
            <label className="block text-xs font-semibold text-zinc-700">유튜브 링크</label>
            <input
              value={youtubeUrl}
              onChange={(e) => onYoutubeUrlChange?.(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              className="w-full rounded-lg border border-zinc-300 px-2.5 py-2 text-xs focus:border-zinc-900 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => onAnalyze?.()}
              disabled={isAnalyzing || !youtubeUrl.trim()}
              className="w-full rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isAnalyzing ? "불러오는 중..." : "불러오기"}
            </button>
            {statusMessage ? (
              <p className="text-[11px] leading-snug text-zinc-600">{statusMessage}</p>
            ) : null}
            {analyzeError ? (
              <p className="text-[11px] leading-snug text-red-600">{analyzeError}</p>
            ) : null}
          </div>

          <div className="flex min-h-0 flex-1 flex-col px-3 pt-3">
            <p className="mb-2 text-xs font-semibold text-zinc-700">트랙 선택</p>
            <div ref={trackListRef} className="min-h-0 flex-1 space-y-1 overflow-y-auto" />
          </div>

          <div className="shrink-0 border-t border-zinc-200 p-3">
            <div className="rounded-xl border border-zinc-200 bg-white p-3 shadow-sm">
              <div className="flex flex-col items-center gap-3">
                <button
                  type="button"
                  onClick={handlePlayPause}
                  disabled={!isPlayerReady}
                  aria-label={isPlaying ? "일시정지" : "재생"}
                  title={isPlaying ? "일시정지" : "재생"}
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-zinc-900 bg-zinc-900 text-white shadow-md transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:border-zinc-300 disabled:bg-zinc-200 disabled:text-zinc-400"
                >
                  {isPlaying ? (
                    <IconPause className="h-6 w-6" />
                  ) : (
                    <IconPlay className="h-7 w-7 pl-0.5" />
                  )}
                </button>
                <p className="w-full text-center font-mono text-xs tabular-nums text-zinc-600">
                  {!isPlayerReady ? playerProgress : songPosition}
                </p>
                <div className="w-full space-y-0.5 text-center">
                  <p className="truncate text-sm font-semibold text-zinc-900" title={titleText}>
                    {titleText}
                  </p>
                  <p className="truncate text-xs text-zinc-500" title={artistText}>
                    {artistText}
                  </p>
                </div>
                <div className="grid w-full grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleCountIn}
                    aria-pressed={isCountIn}
                    className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-[10px] font-medium transition ${
                      isCountIn
                        ? "border-zinc-900 bg-zinc-100 text-zinc-900"
                        : "border-zinc-200 bg-zinc-50 text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    <IconHourglass className="h-5 w-5" />
                    Count-in
                  </button>
                  <button
                    type="button"
                    onClick={handleMetronome}
                    aria-pressed={isMetronome}
                    className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-[10px] font-medium transition ${
                      isMetronome
                        ? "border-zinc-900 bg-zinc-100 text-zinc-900"
                        : "border-zinc-200 bg-zinc-50 text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    <IconMetronome className="h-5 w-5" />
                    Metronome
                  </button>
                  <button
                    type="button"
                    onClick={handleLoop}
                    aria-pressed={isLooping}
                    className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-[10px] font-medium transition ${
                      isLooping
                        ? "border-zinc-900 bg-zinc-100 text-zinc-900"
                        : "border-zinc-200 bg-zinc-50 text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    <IconLoop className="h-5 w-5" />
                    Loop
                  </button>
                  <button
                    type="button"
                    onClick={handlePrint}
                    className="flex flex-col items-center gap-1 rounded-lg border border-zinc-200 bg-zinc-50 px-2 py-2 text-[10px] font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    <IconPrint className="h-5 w-5" />
                    Print
                  </button>
                </div>
                <div className="w-full space-y-2 border-t border-zinc-100 pt-3">
                  <label className="block text-[10px] font-medium text-zinc-500">줌</label>
                  <select
                    value={zoom}
                    onChange={(e) => handleZoomChange(e.target.value)}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs text-zinc-900"
                  >
                    <option value="25">25%</option>
                    <option value="50">50%</option>
                    <option value="75">75%</option>
                    <option value="90">90%</option>
                    <option value="100">100%</option>
                    <option value="110">110%</option>
                    <option value="125">125%</option>
                    <option value="150">150%</option>
                    <option value="200">200%</option>
                  </select>
                  <label className="block text-[10px] font-medium text-zinc-500">레이아웃</label>
                  <select
                    value={layout}
                    onChange={(e) => handleLayoutChange(e.target.value as "page" | "horizontal")}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs text-zinc-900"
                  >
                    <option value="horizontal">Horizontal</option>
                    <option value="page">Page</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <div ref={viewportRef} className="relative min-h-0 flex-1 overflow-auto bg-white p-3">
          <div
            ref={overlayRef}
            className="absolute inset-0 z-20 hidden items-start justify-center bg-black/30 backdrop-blur-[1px]"
          >
            <div className="mt-4 rounded-md bg-white px-3 py-2 text-xs font-medium text-zinc-700 shadow">
              Music sheet is loading
            </div>
          </div>

          {(modelError || renderError) && (
            <div className="absolute left-3 top-3 z-30 rounded-md border border-red-200 bg-white px-3 py-2 text-xs text-red-700 shadow-sm">
              악보 렌더링 오류: {modelError ?? renderError}
            </div>
          )}
          <div className="mx-auto mb-3 mt-1 max-w-[1100px] text-center">
            <p className="text-4xl font-semibold tracking-tight text-zinc-900">{titleText}</p>
            <p className="mt-1 text-2xl text-zinc-700">{artistText}</p>
          </div>
          <div ref={mainRef} className="mx-auto min-h-full w-full max-w-[1100px]" />
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

  const header = [
    `\\tempo ${score.meta.tempo}`,
    `\\ts (${num} ${den})`,
    `\\track "${escapeTex(t.name ?? "Guitar")}"`,
    "\\staff {score tabs}",
    capo > 0 ? `\\capo ${capo}` : "",
    "",
  ]
    .filter(Boolean)
    .join(" ");

  const beatTokens: string[] = [];
  for (const b of t.beats) {
    const lyricText = sanitizeBeatText(b.lyric);
    const chordText = sanitizeBeatText(b.chord);
    const composed = lyricText && chordText ? `${lyricText} ${chordText}` : lyricText ?? chordText;
    const beatText = sanitizeBeatText(composed);
    const playableNotes = (b.notes ?? []).filter((n) => Number(n.fret) >= 0);

    if (playableNotes.length === 0) {
      if (beatText) beatTokens.push(`r{txt "${escapeTex(beatText)}"}`);
      else beatTokens.push("r");
      continue;
    }
    if (playableNotes.length === 1) {
      const n = playableNotes[0];
      const token = `${n.fret}.${n.string}`;
      if (beatText) beatTokens.push(`${token}{txt "${escapeTex(beatText)}"}`);
      else beatTokens.push(token);
      continue;
    }
    const tokens = playableNotes.map((n) => `${n.fret}.${n.string}`);
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
    while (barTokens.length < beatsPerBar) barTokens.push("r");
    barStrings.push(`:${durationDen} ${barTokens.join(" ")} |`);
  }

  const barsPerRow = 4;
  const groupedRows: string[] = [];
  for (let i = 0; i < barStrings.length; i += barsPerRow) {
    groupedRows.push(barStrings.slice(i, i + barsPerRow).join(" "));
  }
  const body = groupedRows.join("\n").replace(/[ \t]+/g, " ").trim();
  return `${header} ${body}`.trim();
}

function escapeTex(input: string): string {
  return input.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function sanitizeBeatText(input: string | null | undefined): string | null {
  if (!input) return null;
  const cleaned = input
    .replace(/[\r\n\t]/g, " ")
    .replace(/[{}|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return null;
  return cleaned.slice(0, 24);
}

function normalizeScoreForRendering(score: AlphaTabScore): AlphaTabScore | null {
  if (!score?.meta || !Array.isArray(score.tracks) || score.tracks.length === 0) return null;
  const track0 = score.tracks[0];
  if (!track0 || !Array.isArray(track0.beats)) return null;

  const beats = track0.beats.map((b) => {
    const notes = Array.isArray(b?.notes)
      ? b.notes
          .map((n) => {
            const string = Number(n?.string);
            const fret = Number(n?.fret);
            const start = Number(n?.start ?? 0);
            const end = Number(n?.end ?? start + 0.25);
            if (!Number.isFinite(string) || !Number.isFinite(fret)) return null;
            if (fret < 0) return null;
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
  });

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

let alphaTabLoadPromise: Promise<AlphaTabModuleLike> | null = null;

function loadAlphaTabUmd(): Promise<AlphaTabModuleLike> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("브라우저 환경에서만 alphaTab을 로드할 수 있습니다."));
  }

  const maybeLoaded = (window as unknown as { alphaTab?: AlphaTabModuleLike }).alphaTab;
  if (maybeLoaded) return Promise.resolve(maybeLoaded);
  if (alphaTabLoadPromise) return alphaTabLoadPromise;

  alphaTabLoadPromise = new Promise<AlphaTabModuleLike>((resolve, reject) => {
    const existing = document.getElementById("alphatab-cdn-script") as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => {
        const loaded = (window as unknown as { alphaTab?: AlphaTabModuleLike }).alphaTab;
        if (loaded) resolve(loaded);
        else reject(new Error("alphaTab 스크립트는 로드되었지만 전역 객체가 없습니다."));
      });
      existing.addEventListener("error", () => {
        reject(new Error("alphaTab 스크립트 로드에 실패했습니다."));
      });
      return;
    }

    const script = document.createElement("script");
    script.id = "alphatab-cdn-script";
    script.async = true;
    script.src = "https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/alphaTab.js";
    script.onload = () => {
      const loaded = (window as unknown as { alphaTab?: AlphaTabModuleLike }).alphaTab;
      if (loaded) resolve(loaded);
      else reject(new Error("alphaTab 스크립트는 로드되었지만 전역 객체가 없습니다."));
    };
    script.onerror = () => {
      reject(new Error("alphaTab 스크립트 로드에 실패했습니다."));
    };
    document.head.appendChild(script);
  });

  return alphaTabLoadPromise;
}
