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
    core: {
      useWorkers: boolean;
      enableLazyLoading: boolean;
      includeNoteBounds: boolean;
      engine: string;
      scriptFile: string | null;
      fontDirectory: string | null;
      logLevel: number;
    };
    display: {
      layoutMode: unknown;
      scale: number;
      padding: number[];
      barsPerRow: number;
      startBar: number;
      barCount: number;
      barCountPerPartial: number;
      justifyLastSystem: boolean;
      stretchForce: number;
    };
    notation: {
      smallGraceTabNotes: boolean;
      extendBendArrowsOnTiedNotes: boolean;
      extendLineEffectsToBeatEnd: boolean;
      slurHeight: number;
      rhythmHeight: number;
      transpositionPitches: number[];
      displayTranspositionPitches: number[];
      rhythmMode?: unknown;
      notationMode?: unknown;
    };
    player: {
      enablePlayer: boolean;
      enableCursor: boolean;
      enableElementHighlighting: boolean;
      enableAnimatedBeatCursor: boolean;
      enableUserInteraction: boolean;
      bufferTimeInMilliseconds: number;
      nativeBrowserSmoothScroll: boolean;
      scrollMode: unknown;
      scrollOffsetX: number;
      scrollOffsetY: number;
      scrollSpeed: number;
      soundFont: string;
      scrollElement?: HTMLElement;
    };
  };
  LayoutMode: {
    Horizontal: unknown;
    Page: unknown;
  };
  ScrollMode?: {
    Continuous?: unknown;
  };
  TabRhythmMode?: {
    Automatic?: unknown;
  };
  NotationMode?: {
    GuitarPro?: unknown;
  };
  synth: {
    PlayerState: {
      Playing: unknown;
    };
  };
  midi?: {
    MidiEventType?: {
      AlphaTabMetronome?: unknown;
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
  endTime?: number;
  endTick?: number;
  isReadyForPlayback?: boolean;
  playerState?: unknown;
  masterVolume?: number;
  countInVolume: number;
  metronomeVolume: number;
  isLooping: boolean;
  error?: {
    on: (cb: (error: unknown) => void) => void;
  };
  scoreLoaded: {
    on: (cb: (score: { tracks: Array<{ index: number; name: string }> }) => void) => void;
  };
  activeBeatsChanged?: {
    on: (cb: (e: { activeBeats?: unknown[] }) => void) => void;
  };
  beatMouseDown?: {
    on: (cb: (beat: unknown) => void) => void;
  };
  beatMouseMove?: {
    on: (cb: (beat: unknown) => void) => void;
  };
  beatMouseUp?: {
    on: (cb: (beat: unknown | null) => void) => void;
  };
  noteMouseMove?: {
    on: (cb: (note: unknown) => void) => void;
  };
  noteMouseDown?: {
    on: (cb: (note: unknown) => void) => void;
  };
  noteMouseUp?: {
    on: (cb: (note: unknown | null) => void) => void;
  };
  midiLoad?: {
    on: (cb: (midiFile: unknown) => void) => void;
  };
  midiLoaded?: {
    on: (cb: (e: { endTime?: number }) => void) => void;
  };
  midiEventsPlayed?: {
    on: (cb: (e: { events?: Array<{ isMetronome?: boolean }> }) => void) => void;
  };
  midiEventsPlayedFilter?: unknown[];
  midiTickShift?: number;
  tickPosition?: number;
  timePosition?: number;
  tickCache?: {
    findBeat: (
      trackIndexes: Set<number>,
      tick: number,
    ) => {
      beat?: unknown;
      start?: number;
      end?: number;
      tickDuration?: number;
      duration?: number; // ms
    } | null;
  } | null;
  enumerateOutputDevices?: () => Promise<Array<{ id?: string; label?: string }>>;
  setOutputDevice?: (device: { id?: string; label?: string } | null) => Promise<void>;
  getOutputDevice?: () => Promise<{ id?: string; label?: string } | null>;
  playbackRange?: { startTick: number; endTick: number } | null;
  playbackRangeChanged?: {
    on: (cb: (e: { playbackRange?: { startTick: number; endTick: number } | null }) => void) => void;
  };
  playbackRangeHighlightChanged?: {
    on: (cb: () => void) => void;
  };
  playedBeatChanged?: {
    on: (cb: (beat: unknown) => void) => void;
  };
  playerFinished?: {
    on: (cb: () => void) => void;
  };
  postRenderFinished?: {
    on: (cb: () => void) => void;
  };
  resize?: {
    on: (cb: (args: { newWidth?: number; settings?: { display?: { scale?: number } } }) => void) => void;
  };
  playbackSpeed?: number;
  play?: () => boolean;
  pause?: () => void;
  playBeat?: (beat: unknown) => void;
  playNote?: (note: unknown) => void;
  loadMidiForScore?: () => void;
  resetSoundFonts?: () => void;
  renderStarted: { on: (cb: () => void) => void };
  renderFinished: { on: (cb: () => void) => void };
  soundFontLoad: { on: (cb: (e: { loaded: number; total: number }) => void) => void };
  soundFontLoaded?: { on: (cb: () => void) => void };
  settingsUpdated?: { on: (cb: () => void) => void };
  playerReady: { on: (cb: () => void) => void };
  playerStateChanged: { on: (cb: (e: { state: unknown }) => void) => void };
  playerPositionChanged: {
    on: (cb: (e: { currentTime: number; endTime: number }) => void) => void;
  };
  renderTracks: (tracks: unknown[]) => void;
  changeTrackMute?: (tracks: unknown[], mute: boolean) => void;
  changeTrackSolo?: (tracks: unknown[], solo: boolean) => void;
  changeTrackVolume?: (tracks: unknown[], volume: number) => void;
  highlightPlaybackRange?: (startBeat: unknown, endBeat: unknown) => void;
  applyPlaybackRangeFromHighlight?: () => void;
  clearPlaybackRangeHighlight?: () => void;
  downloadMidi?: () => void;
  boundsLookup?: unknown;
  customCursorHandler?: unknown;
  customScrollHandler?: unknown;
  updateSettings: () => void;
  render: () => void;
  tex: (tex: string) => void;
  print: (width?: string, additionalSettings?: unknown) => void;
  scrollToCursor?: () => void;
  playPause: () => void;
  stop: () => void;
  destroy: () => void;
};

interface ScoreViewerProps {
  score: AlphaTabScore | null;
  alphaTex?: string | null;
  songTitle?: string | null;
  songArtist?: string | null;
  songLyrics?: string | null;
  songChords?: string[];
  /** 사이드바: 유튜브 URL + 불러오기 */
  youtubeUrl?: string;
  onYoutubeUrlChange?: (value: string) => void;
  onAnalyze?: () => void;
  onPreviewMidi?: (file: File) => Promise<{ ok: boolean; message?: string }>;
  isAnalyzing?: boolean;
  statusMessage?: string | null;
  analyzeError?: string | null;
  analyzeProgress?: number | null;
}

export const ScoreViewer: React.FC<ScoreViewerProps> = ({
  score,
  alphaTex = null,
  songTitle,
  songArtist,
  songLyrics,
  youtubeUrl = "",
  onYoutubeUrlChange,
  onAnalyze,
  onPreviewMidi,
  isAnalyzing = false,
  statusMessage,
  analyzeError,
  analyzeProgress = null,
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
  const [remainingTime, setRemainingTime] = useState("--:--");
  const [playerProgress, setPlayerProgress] = useState("0%");
  const [isCountIn, setIsCountIn] = useState(false);
  const [isMetronome, setIsMetronome] = useState(false);
  const [isLooping, setIsLooping] = useState(false);
  const [zoom, setZoom] = useState("100");
  const [layout, setLayout] = useState<"page" | "horizontal">("page");
  const [isStudyMode, setIsStudyMode] = useState(false);
  const [allowSeekByClick, setAllowSeekByClick] = useState(true);
  const [midiPreviewName, setMidiPreviewName] = useState<string | null>(null);
  const [midiPreviewError, setMidiPreviewError] = useState<string | null>(null);
  const [isMidiPreviewLoading, setIsMidiPreviewLoading] = useState(false);
  const [activeBeatText, setActiveBeatText] = useState<string>("대기 중");
  const [selectionState, setSelectionState] = useState<string>("선택 없음");
  const [hoveredNoteText, setHoveredNoteText] = useState<string>("노트 정보 없음");
  const [abRangeMs, setAbRangeMs] = useState<number | null>(null);
  const [masterVolume, setMasterVolume] = useState(1);
  const [metronomeVolumeRatio, setMetronomeVolumeRatio] = useState(0);
  const [apiErrorMessage, setApiErrorMessage] = useState<string | null>(null);
  const [midiStageText, setMidiStageText] = useState("MIDI 대기");
  const [midiEventCount, setMidiEventCount] = useState(0);
  const [metronomeTickCount, setMetronomeTickCount] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [speedTrainerEnabled, setSpeedTrainerEnabled] = useState(false);
  const [playedBeatText, setPlayedBeatText] = useState("재생 비트 정보 없음");
  const [renderStageText, setRenderStageText] = useState("렌더 대기");
  const [playerStateText, setPlayerStateText] = useState("정지");
  const [outputDevices, setOutputDevices] = useState<Array<{ id?: string; label?: string }>>([]);
  const [selectedOutputDeviceId, setSelectedOutputDeviceId] = useState("default");
  const selectionStartMsRef = useRef<number | null>(null);
  const selectionStartTickRef = useRef<number | null>(null);
  const previousSecondRef = useRef(-1);
  const dragStartBeatRef = useRef<unknown | null>(null);

  useEffect(() => {
    if (isStudyMode) {
      setAllowSeekByClick(false);
    }
  }, [isStudyMode]);

  const workingScore = score ?? nullBaseline;
  const hasBackendAlphaTex = Boolean(alphaTex && alphaTex.trim().length > 0);

  const normalizedScore = useMemo(
    () => (hasBackendAlphaTex ? null : normalizeScoreForRendering(workingScore)),
    [hasBackendAlphaTex, workingScore],
  );
  const modelError =
    !hasBackendAlphaTex && normalizedScore === null ? "악보 데이터 형식이 올바르지 않습니다." : null;

  useEffect(() => {
    if (!mainRef.current) return;

    let disposed = false;
    mainRef.current.innerHTML = "";
    trackListRef.current?.replaceChildren();
    previousSecondRef.current = -1;

    if (!hasBackendAlphaTex && !normalizedScore) return;

    const tex = hasBackendAlphaTex ? (alphaTex as string) : buildAlphaTex(normalizedScore as AlphaTabScore);

    (async () => {
      const alphaTab = await loadAlphaTabUmd();
      if (disposed || !mainRef.current) return;
      alphaTabModuleRef.current = alphaTab;

      const settings = new alphaTab.Settings();
      settings.display.layoutMode =
        layout === "horizontal" ? alphaTab.LayoutMode.Horizontal : alphaTab.LayoutMode.Page;
      settings.display.scale = Number.parseInt(zoom, 10) / 100;
      settings.display.padding = [10, 10, 10, 10];
      settings.display.barsPerRow = isStudyMode && layout === "page" ? 4 : -1;
      settings.display.startBar = 1;
      settings.display.barCount = isStudyMode ? 16 : -1;
      settings.display.barCountPerPartial = 8;
      settings.display.justifyLastSystem = true;
      settings.display.stretchForce = isStudyMode ? 0.92 : 1;
      settings.core.useWorkers = true;
      settings.core.enableLazyLoading = true;
      settings.core.includeNoteBounds = isStudyMode;
      settings.core.engine = "svg";
      settings.core.scriptFile =
        "https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/alphaTab.js";
      settings.core.fontDirectory =
        "https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/";
      // 개발 중 콘솔 노이즈를 줄이고, 프로덕션에서만 경고 이상 로그를 남긴다.
      settings.core.logLevel = process.env.NODE_ENV === "development" ? 2 : 3;
      // notation.* 는 렌더링 표현 품질을 제어하며, MIDI 자체 데이터는 변경하지 않는다.
      settings.notation.smallGraceTabNotes = true;
      settings.notation.extendBendArrowsOnTiedNotes = true;
      settings.notation.extendLineEffectsToBeatEnd = false;
      settings.notation.slurHeight = 5;
      settings.notation.rhythmHeight = isStudyMode ? 30 : 25;
      settings.notation.transpositionPitches = [0];
      settings.notation.displayTranspositionPitches = [0];
      if (alphaTab.NotationMode?.GuitarPro !== undefined) {
        settings.notation.notationMode = alphaTab.NotationMode.GuitarPro;
      }
      if (alphaTab.TabRhythmMode?.Automatic !== undefined) {
        settings.notation.rhythmMode = alphaTab.TabRhythmMode.Automatic;
      }
      settings.player.enablePlayer = true;
      settings.player.enableCursor = true;
      settings.player.enableElementHighlighting = true;
      settings.player.enableAnimatedBeatCursor = true;
      settings.player.enableUserInteraction = allowSeekByClick;
      settings.player.bufferTimeInMilliseconds = isStudyMode ? 460 : 380;
      settings.player.nativeBrowserSmoothScroll = !isStudyMode;
      if (alphaTab.ScrollMode?.Continuous !== undefined) {
        settings.player.scrollMode = alphaTab.ScrollMode.Continuous;
      }
      settings.player.scrollOffsetX = 0;
      settings.player.scrollOffsetY = isStudyMode ? -24 : -12;
      // nativeBrowserSmoothScroll=false일 때에만 scrollSpeed가 유효하다.
      settings.player.scrollSpeed = isStudyMode ? 220 : 300;
      settings.player.soundFont =
        "https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2";
      if (viewportRef.current) {
        settings.player.scrollElement = viewportRef.current;
      }

      const api = new alphaTab.AlphaTabApi(mainRef.current, settings);
      apiRef.current = api;
      setApiErrorMessage(null);
      setMasterVolume(Math.max(0, Math.min(1, api.masterVolume ?? 1)));
      setMetronomeVolumeRatio(Math.max(0, Math.min(1, api.metronomeVolume ?? 0)));
      setPlaybackSpeed(api.playbackSpeed ?? 1);
      setMidiEventCount(0);
      setMetronomeTickCount(0);
      setMidiStageText("MIDI 대기");
      setOutputDevices([]);
      setSelectedOutputDeviceId("default");

      if ("customCursorHandler" in api) {
        api.customCursorHandler = {
          onAttach: () => {},
          onDetach: () => {},
          placeBarCursor: (barCursor: { setBounds: (x: number, y: number, w: number, h: number) => void }, beatBounds: { barBounds?: { masterBarBounds?: { visualBounds?: { x: number; y: number; w: number; h: number } } } }) => {
            const b = beatBounds?.barBounds?.masterBarBounds?.visualBounds;
            if (!b) return;
            barCursor.setBounds(b.x, b.y, b.w, b.h);
          },
          placeBeatCursor: (
            beatCursor: {
              setBounds: (x: number, y: number, w: number, h: number) => void;
              transitionToX: (duration: number, x: number) => void;
            },
            beatBounds: { barBounds?: { masterBarBounds?: { visualBounds?: { y: number; h: number } } } },
            startBeatX: number,
          ) => {
            const bar = beatBounds?.barBounds?.masterBarBounds?.visualBounds;
            if (!bar) return;
            beatCursor.transitionToX(0, startBeatX);
            beatCursor.setBounds(startBeatX, bar.y, 2, bar.h);
          },
          transitionBeatCursor: () => {},
        };
      }
      if ("customScrollHandler" in api) {
        api.customScrollHandler = {
          forceScrollTo: () => {},
          onBeatCursorUpdating: () => {},
        };
      }

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

      api.scoreLoaded.on((loadedScore) => {
        const list = trackListRef.current;
        if (!list) return;
        list.replaceChildren();
        loadedScore.tracks.forEach((track) => {
          const row = document.createElement("div");
          row.className = "rounded-md border border-zinc-200 bg-white p-1.5";
          const mainBtn = createTrackItem(track as never);
          row.appendChild(mainBtn);

          const controls = document.createElement("div");
          controls.className = "mt-1 grid grid-cols-3 gap-1";

          const muteBtn = document.createElement("button");
          muteBtn.type = "button";
          muteBtn.className = "rounded border border-zinc-300 px-1 py-1 text-[10px] text-zinc-700 hover:bg-zinc-100";
          muteBtn.textContent = "Mute";
          muteBtn.onclick = () => api.changeTrackMute?.([track as never], true);
          controls.appendChild(muteBtn);

          const soloBtn = document.createElement("button");
          soloBtn.type = "button";
          soloBtn.className = "rounded border border-zinc-300 px-1 py-1 text-[10px] text-zinc-700 hover:bg-zinc-100";
          soloBtn.textContent = "Solo";
          soloBtn.onclick = () => api.changeTrackSolo?.([track as never], true);
          controls.appendChild(soloBtn);

          const volBtn = document.createElement("button");
          volBtn.type = "button";
          volBtn.className = "rounded border border-zinc-300 px-1 py-1 text-[10px] text-zinc-700 hover:bg-zinc-100";
          volBtn.textContent = "Vol 80%";
          volBtn.onclick = () => api.changeTrackVolume?.([track as never], 0.8);
          controls.appendChild(volBtn);

          row.appendChild(controls);
          list.appendChild(row);
        });
        markActiveTracks();
        const hasNoteBounds = Boolean(api.boundsLookup);
        if (isStudyMode) {
          setHoveredNoteText(hasNoteBounds ? "노트 탐색 준비됨" : "노트 경계 정보 없음");
        }
        const totalMs = api.endTime ?? 0;
        if (totalMs > 0) {
          setRemainingTime(formatDurationMs(totalMs));
        } else {
          setRemainingTime("--:--");
        }
        if (api.enumerateOutputDevices) {
          api
            .enumerateOutputDevices()
            .then((devices) => {
              if (disposed) return;
              setOutputDevices(devices);
              void (async () => {
                const current = await api.getOutputDevice?.();
                setSelectedOutputDeviceId(current?.id ?? "default");
              })();
            })
            .catch(() => {
              if (disposed) return;
              setOutputDevices([]);
              setSelectedOutputDeviceId("default");
            });
        }
      });

      api.renderStarted.on(() => {
        if (overlayRef.current) overlayRef.current.style.display = "flex";
        markActiveTracks();
        setRenderStageText("레이아웃/렌더 시작");
      });

      api.renderFinished.on(() => {
        if (overlayRef.current) overlayRef.current.style.display = "none";
        setRenderStageText("렌더 엔진 완료");
      });
      api.postRenderFinished?.on(() => {
        setRenderStageText("후처리 포함 렌더 완료");
      });

      api.soundFontLoad.on((e) => {
        const percentage = Math.floor((e.loaded / e.total) * 100);
        setPlayerProgress(`${percentage}%`);
      });
      api.soundFontLoaded?.on(() => {
        setPlayerProgress("100%");
        setIsPlayerReady(Boolean(api.isReadyForPlayback ?? true));
        setPlayerStateText("사운드폰트 로딩 완료");
      });

      api.playerReady.on(() => {
        setIsPlayerReady(Boolean(api.isReadyForPlayback ?? true));
        setPlayerStateText("준비됨");
      });
      api.settingsUpdated?.on(() => {
        setZoom(String(Math.round((api.settings.display.scale ?? 1) * 100)));
        setLayout(
          api.settings.display.layoutMode === alphaTab.LayoutMode.Horizontal ? "horizontal" : "page",
        );
      });

      api.playerStateChanged.on((e) => {
        setIsPlaying(e.state === alphaTab.synth.PlayerState.Playing);
        setPlayerStateText(
          e.state === alphaTab.synth.PlayerState.Playing ? "재생 중" : "일시정지/정지",
        );
      });

      api.playerPositionChanged.on((e) => {
        const currentSeconds = (e.currentTime / 1000) | 0;
        if (currentSeconds === previousSecondRef.current) return;
        previousSecondRef.current = currentSeconds;
        setSongPosition(`${formatDurationMs(e.currentTime)} / ${formatDurationMs(e.endTime)}`);
        const remain = Math.max(0, e.endTime - e.currentTime);
        setRemainingTime(formatDurationMs(remain));
        const denom = Math.max(1, api.endTime ?? e.endTime);
        const progress = Math.max(0, Math.min(100, (e.currentTime / denom) * 100));
        setPlayerProgress(`${Math.floor(progress)}%`);
        const tick = Number(api.tickPosition ?? 0);
        if (api.tickCache && Number.isFinite(tick)) {
          const lookup = api.tickCache.findBeat(new Set(api.tracks.map((t) => t.index)), tick);
          if (lookup?.currentBeat) {
            setPlayedBeatText(`tickCache 비트 추적 중 (tick ${Math.floor(tick)})`);
          }
        }
        api.scrollToCursor?.();
      });

      if (alphaTab.midi?.MidiEventType?.AlphaTabMetronome !== undefined) {
        api.midiEventsPlayedFilter = [alphaTab.midi.MidiEventType.AlphaTabMetronome];
      }
      api.midiLoad?.on(() => {
        setMidiStageText("MIDI 생성/로딩 중...");
      });
      api.midiLoaded?.on((e) => {
        setMidiStageText("MIDI 로딩 완료");
        if (typeof e.endTime === "number" && e.endTime > 0) {
          setRemainingTime(formatDurationMs(e.endTime));
        }
      });
      api.midiEventsPlayed?.on((e) => {
        const events = e.events ?? [];
        setMidiEventCount((prev) => prev + events.length);
        const metronomeTicks = events.filter((evt) => evt.isMetronome).length;
        if (metronomeTicks > 0) {
          setMetronomeTickCount((prev) => prev + metronomeTicks);
        }
      });

      api.error?.on((error) => {
        const message = error instanceof Error ? error.message : "재생/렌더 처리 중 오류가 발생했습니다.";
        const anyErr = error as unknown as { type?: unknown };
        const errorType = anyErr?.type;

        // AlphaTabErrorType: General / Format / AlphaTex
        if (errorType !== undefined && "AlphaTabErrorType" in alphaTabModuleRef.current!) {
          const t = (alphaTab as unknown as { AlphaTabErrorType?: Record<string, number> }).AlphaTabErrorType;
          const alphaTexType = t?.AlphaTex;
          const formatType = t?.Format;
          const generalType = t?.General;

          if (typeof alphaTexType === "number" && errorType === alphaTexType) {
            setApiErrorMessage(`AlphaTex 변환/문법 오류 가능성: ${message}`);
            return;
          }
          if (typeof formatType === "number" && errorType === formatType) {
            setApiErrorMessage(`MIDI/스코어 구조 오류 가능성: ${message}`);
            return;
          }
          if (typeof generalType === "number" && errorType === generalType) {
            setApiErrorMessage(`알파탭 처리 오류: ${message}`);
            return;
          }
        }

        setApiErrorMessage(message);
      });

      api.activeBeatsChanged?.on((e) => {
        const count = e.activeBeats?.length ?? 0;
        setActiveBeatText(count > 0 ? `현재 활성 비트: ${count}` : "활성 비트 없음");
      });

      api.beatMouseDown?.on((beat) => {
        dragStartBeatRef.current = beat;
        const startMs = getBeatPlaybackMs(beat);
        selectionStartMsRef.current = startMs;
        selectionStartTickRef.current = getBeatTick(beat);
        if (startMs === null && selectionStartTickRef.current !== null && api.tickCache) {
          const resolved = resolveMsFromTick(api, selectionStartTickRef.current);
          selectionStartMsRef.current = resolved;
        }
        setSelectionState("구간 선택 시작");
      });
      api.beatMouseMove?.on((beat) => {
        if (!dragStartBeatRef.current || !beat) return;
        api.highlightPlaybackRange?.(dragStartBeatRef.current, beat);
        setSelectionState("구간 선택 중...");
      });
      api.beatMouseUp?.on((beat) => {
        if (!dragStartBeatRef.current || !beat) {
          dragStartBeatRef.current = null;
          selectionStartMsRef.current = null;
          return;
        }
        api.highlightPlaybackRange?.(dragStartBeatRef.current, beat);
        api.applyPlaybackRangeFromHighlight?.();
        const startTick = selectionStartTickRef.current;
        const endTick = getBeatTick(beat);
        let rangeMs =
          startTick !== null && endTick !== null && startTick <= endTick
            ? resolveRangeMsFromTickCache(api, startTick, endTick)
            : null;

        if (rangeMs === null) {
          // fallback: 구간 길이 표시만 가능한 근사
          const startMs = selectionStartMsRef.current;
          const endMs = getBeatPlaybackMs(beat);
          if (startMs !== null && endMs !== null) {
            rangeMs = Math.abs(endMs - startMs);
          } else if (startTick !== null && endTick !== null) {
            const a = resolveMsFromTick(api, startTick);
            const b = resolveMsFromTick(api, endTick);
            if (a !== null && b !== null) rangeMs = Math.abs(b - a);
          }
        }

        if (rangeMs !== null) setAbRangeMs(rangeMs);
        setSelectionState("선택 구간 재생 범위 적용됨");
        dragStartBeatRef.current = null;
        selectionStartMsRef.current = null;
        selectionStartTickRef.current = null;
      });

      api.noteMouseMove?.on((note) => {
        const n = note as { string?: number; fret?: number };
        if (typeof n?.string === "number" && typeof n?.fret === "number") {
          setHoveredNoteText(`노트: ${n.string}번줄 ${n.fret}프렛`);
        }
      });
      api.noteMouseDown?.on((note) => {
        if (isStudyMode) {
          api.playNote?.(note);
        }
      });
      api.noteMouseUp?.on((note) => {
        if (!note || !isStudyMode) return;
        api.playNote?.(note);
      });
      api.playedBeatChanged?.on((beat) => {
        const b = beat as { id?: number };
        setPlayedBeatText(typeof b?.id === "number" ? `재생 비트 ID: ${b.id}` : "재생 비트 갱신");
      });
      api.playbackRangeChanged?.on((e) => {
        if (e.playbackRange) {
          const { startTick, endTick } = e.playbackRange;
          const rangeMs = resolveRangeMsFromTickCache(api, startTick, endTick);
          if (rangeMs !== null) setAbRangeMs(rangeMs);
          setSelectionState(
            `재생 범위 Tick: ${Math.floor(e.playbackRange.startTick)}~${Math.floor(e.playbackRange.endTick)}`,
          );
        } else {
          setSelectionState("재생 범위 없음");
        }
      });
      api.playbackRangeHighlightChanged?.on(() => {
        setSelectionState("선택 하이라이트 변경됨");
      });
      api.playerFinished?.on(() => {
        setPlayerStateText("재생 완료");
        if (!speedTrainerEnabled) return;
        const nextSpeed = Math.min(1.5, (api.playbackSpeed ?? 1) + 0.05);
        api.playbackSpeed = nextSpeed;
        setPlaybackSpeed(nextSpeed);
      });
      api.resize?.on((args) => {
        const width = args.newWidth ?? 0;
        const nextScale = width > 1500 ? 1.15 : width > 1100 ? 1 : 0.9;
        setZoom(String(Math.round(nextScale * 100)));
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
  }, [allowSeekByClick, isStudyMode, layout, normalizedScore, speedTrainerEnabled, zoom, alphaTex, hasBackendAlphaTex]);

  const handlePlayPause = () => {
    const canPlay = isPlayerReady && (apiRef.current?.isReadyForPlayback ?? true);
    if (!canPlay) return;
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
    if (apiRef.current) {
      const target = next ? Math.max(0.05, metronomeVolumeRatio) : 0;
      apiRef.current.metronomeVolume = target;
    }
  };

  const handleLoop = () => {
    const next = !isLooping;
    setIsLooping(next);
    if (apiRef.current) apiRef.current.isLooping = next;
  };

  const handlePrint = () => {
    apiRef.current?.print();
  };

  const handlePrintA4 = () => {
    apiRef.current?.print(undefined, {
      display: { scale: 0.8, stretchForce: 0.8 },
    });
  };

  const handleOutputDeviceChange = async (deviceId: string) => {
    setSelectedOutputDeviceId(deviceId);
    const api = apiRef.current;
    if (!api?.setOutputDevice) return;
    if (deviceId === "default") {
      await api.setOutputDevice(null);
      return;
    }
    const selected = outputDevices.find((d) => d.id === deviceId) ?? null;
    await api.setOutputDevice(selected);
  };

  const handleResetSoundFonts = () => {
    apiRef.current?.resetSoundFonts?.();
    setApiErrorMessage("사운드폰트 캐시를 초기화했습니다. 필요 시 다시 로딩됩니다.");
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

  const handleMidiFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!file) return;

    const isMidi =
      file.type === "audio/midi" ||
      file.type === "audio/x-midi" ||
      file.name.toLowerCase().endsWith(".mid") ||
      file.name.toLowerCase().endsWith(".midi");
    if (!isMidi) {
      setMidiPreviewError("MIDI 파일(.mid, .midi)만 업로드할 수 있습니다.");
      return;
    }

    if (!onPreviewMidi) {
      setMidiPreviewError("MIDI 미리듣기 기능이 연결되지 않았습니다.");
      return;
    }

    try {
      setIsMidiPreviewLoading(true);
      const result = await onPreviewMidi(file);
      if (!result.ok) {
        setMidiPreviewError(result.message || "MIDI 로드 중 오류가 발생했습니다.");
        return;
      }
      setMidiPreviewName(file.name);
      setMidiPreviewError(result.message ?? null);
    } catch (e) {
      const message = e instanceof Error ? e.message : "MIDI 로드 중 오류가 발생했습니다.";
      setMidiPreviewError(message);
    } finally {
      setIsMidiPreviewLoading(false);
    }
  };

  const titleText = workingScore.meta.title || songTitle || "빈 악보";
  const artistText = (songArtist ?? "").trim();

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
            {analyzeProgress !== null ? (
              <div className="space-y-1">
                <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200">
                  <div
                    className="h-full bg-zinc-900 transition-all duration-300"
                    style={{ width: `${Math.max(0, Math.min(100, analyzeProgress))}%` }}
                  />
                </div>
                <p className="text-[10px] text-zinc-500">진행률 {Math.floor(analyzeProgress)}%</p>
              </div>
            ) : null}
            {analyzeError ? (
              <p className="text-[11px] leading-snug text-red-600">{analyzeError}</p>
            ) : null}
            <div className="mt-3 space-y-1 rounded-lg border border-zinc-200 bg-white p-2">
              <p className="text-[11px] font-semibold text-zinc-700">MIDI 미리듣기</p>
              <input
                type="file"
                accept=".mid,.midi,audio/midi,audio/x-midi"
                onChange={handleMidiFileChange}
                disabled={isMidiPreviewLoading}
                className="w-full text-[11px] text-zinc-700 file:mr-2 file:rounded-md file:border file:border-zinc-300 file:bg-zinc-100 file:px-2 file:py-1 file:text-[11px] file:font-medium file:text-zinc-700 hover:file:bg-zinc-200"
              />
              {isMidiPreviewLoading ? (
                <p className="text-[11px] leading-snug text-zinc-600">MIDI를 변환 중입니다...</p>
              ) : null}
              {midiPreviewName ? (
                <p className="text-[11px] leading-snug text-zinc-600">
                  로드됨: {midiPreviewName}
                </p>
              ) : null}
              {midiPreviewError ? (
                <p className="text-[11px] leading-snug text-red-600">{midiPreviewError}</p>
              ) : null}
            </div>
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
                <p className="w-full text-center text-[11px] text-zinc-500">
                  남은 시간 {remainingTime}
                  {abRangeMs !== null ? ` · AB ${formatDurationMs(abRangeMs)}` : ""}
                </p>
                <div className="w-full space-y-0.5 text-center">
                  <p className="truncate text-sm font-semibold text-zinc-900" title={titleText}>
                    {titleText}
                  </p>
                  {artistText ? (
                    <p className="truncate text-xs text-zinc-500" title={artistText}>
                      {artistText}
                    </p>
                  ) : null}
                  {songLyrics?.trim() ? (
                    <p
                      className="max-h-14 overflow-hidden pt-1 text-[11px] leading-snug text-zinc-500"
                      title={songLyrics}
                    >
                      {songLyrics}
                    </p>
                  ) : null}
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
                  <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2 text-[10px] text-zinc-600">
                    <p>{activeBeatText}</p>
                    <p>{selectionState}</p>
                    <p>{hoveredNoteText}</p>
                    {apiErrorMessage ? <p className="text-red-600">오류: {apiErrorMessage}</p> : null}
                    <p>렌더 상태: {renderStageText}</p>
                    <p>플레이어 상태: {playerStateText}</p>
                    <p>총 길이: {apiRef.current?.endTime ? formatDurationMs(apiRef.current.endTime) : "--:--"}</p>
                    <p>총 Tick: {Math.floor(apiRef.current?.endTick ?? 0)}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsStudyMode((prev) => !prev)}
                    aria-pressed={isStudyMode}
                    className={`h-9 w-full rounded-lg border px-2 text-xs font-medium transition ${
                      isStudyMode
                        ? "border-amber-500 bg-amber-50 text-amber-800"
                        : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    {isStudyMode ? "학습 모드 ON (16마디/4마디행)" : "학습 모드 OFF"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setAllowSeekByClick((prev) => !prev)}
                    aria-pressed={allowSeekByClick}
                    className={`h-9 w-full rounded-lg border px-2 text-xs font-medium transition ${
                      allowSeekByClick
                        ? "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100"
                        : "border-amber-500 bg-amber-50 text-amber-800"
                    }`}
                    title="재생 중 악보 클릭 시 탐색(Seek) 동작"
                  >
                    {allowSeekByClick ? "클릭 탐색 ON" : "클릭 탐색 OFF (실수 방지)"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      apiRef.current?.clearPlaybackRangeHighlight?.();
                      setSelectionState("선택 구간 하이라이트 해제");
                      setAbRangeMs(null);
                    }}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    선택 구간 해제
                  </button>
                  <button
                    type="button"
                    onClick={() => apiRef.current?.downloadMidi?.()}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    MIDI 다운로드
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const api = apiRef.current;
                      if (!api) return;
                      if (isPlaying) api.pause?.();
                      else api.play?.();
                    }}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    {isPlaying ? "pause()" : "play()"}
                  </button>
                  <button
                    type="button"
                    onClick={() => apiRef.current?.loadMidiForScore?.()}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    MIDI 재생성(loadMidiForScore)
                  </button>
                  <button
                    type="button"
                    onClick={handleResetSoundFonts}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    사운드폰트 메모리 초기화
                  </button>
                  <button
                    type="button"
                    onClick={handlePrintA4}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100"
                  >
                    A4 인쇄 최적화
                  </button>
                  <label className="block text-[10px] font-medium text-zinc-500">출력 장치</label>
                  <select
                    value={selectedOutputDeviceId}
                    onChange={(e) => {
                      void handleOutputDeviceChange(e.target.value).catch((err) => {
                        const message =
                          err instanceof Error ? err.message : "출력 장치 변경 중 오류가 발생했습니다.";
                        setApiErrorMessage(message);
                      });
                    }}
                    className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-xs text-zinc-900"
                  >
                    <option value="default">기본 장치</option>
                    {outputDevices.map((d, idx) => (
                      <option key={d.id ?? `device-${idx}`} value={d.id ?? ""}>
                        {d.label || `장치 ${idx + 1}`}
                      </option>
                    ))}
                  </select>
                  <label className="block text-[10px] font-medium text-zinc-500">Master Volume</label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={masterVolume}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setMasterVolume(v);
                      if (apiRef.current) apiRef.current.masterVolume = v;
                    }}
                    className="w-full"
                  />
                  <label className="block text-[10px] font-medium text-zinc-500">Metronome Volume</label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={metronomeVolumeRatio}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setMetronomeVolumeRatio(v);
                      if (apiRef.current && isMetronome) apiRef.current.metronomeVolume = v;
                    }}
                    className="w-full"
                  />
                  <label className="block text-[10px] font-medium text-zinc-500">Playback Speed</label>
                  <input
                    type="range"
                    min={0.5}
                    max={1.5}
                    step={0.05}
                    value={playbackSpeed}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setPlaybackSpeed(v);
                      if (apiRef.current) apiRef.current.playbackSpeed = v;
                    }}
                    className="w-full"
                  />
                  <button
                    type="button"
                    onClick={() => setSpeedTrainerEnabled((prev) => !prev)}
                    className={`h-9 w-full rounded-lg border px-2 text-xs font-medium transition ${
                      speedTrainerEnabled
                        ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                        : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    {speedTrainerEnabled ? "속도 트레이너 ON (+5%)" : "속도 트레이너 OFF"}
                  </button>
                  <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2 text-[10px] text-zinc-600">
                    <p>{midiStageText}</p>
                    <p>MIDI 이벤트 수: {midiEventCount}</p>
                    <p>메트로놈 틱 수: {metronomeTickCount}</p>
                    <p>midiTickShift: {Math.floor(apiRef.current?.midiTickShift ?? 0)}</p>
                    <p>{playedBeatText}</p>
                  </div>
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
            {artistText ? <p className="mt-1 text-2xl text-zinc-700">{artistText}</p> : null}
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
  const tempo = Number.isFinite(Number(score.meta.tempo)) ? Number(score.meta.tempo) : 90;

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

  const baseDen = 16;
  const quarterSec = 60 / Math.max(1, tempo);
  const beats = [...t.beats].sort((a, b) => a.time - b.time);
  const beatTimes = beats.map((b) => b.time);
  const deltas = beatTimes
    .slice(1)
    .map((time, i) => time - beatTimes[i])
    .filter((d) => Number.isFinite(d) && d > 1e-6);
  // normalizeScoreForRendering에서 beat 간격을 0.125초 버킷으로 압축할 수 있으므로,
  // base unit은 tempo에서 계산한 값이 아니라 "데이터의 중앙 delta"를 우선 사용한다.
  const fallbackBaseUnitSec = quarterSec / 4; // 1/16 note duration(이론치)
  const sortedDeltas = [...deltas].sort((a, b) => a - b);
  const medianDelta = sortedDeltas.length > 0 ? sortedDeltas[(sortedDeltas.length / 2) | 0] : fallbackBaseUnitSec;
  const baseUnitSec =
    medianDelta > fallbackBaseUnitSec * 0.25 && medianDelta < fallbackBaseUnitSec * 4
      ? medianDelta
      : fallbackBaseUnitSec;
  const measureSec = num * quarterSec * (4 / Math.max(1, den));
  const measureUnitsTarget = Math.max(1, Math.round(measureSec / baseUnitSec));

  // :16 기준이 1/16 단위라서 세그먼트가 이 그리드의 정수 배로 나오도록 :32는 제외한다.
  const allowedDenByUnits = [16, 8, 4, 2, 1];
  const durationSecondsToDen = (durationSec: number): number => {
    const units = durationSec / baseUnitSec;
    // durationChange의 value는 분모(예: :4, :8)로 해석된다.
    // baseDen=16을 기준으로 units = 16/den 관계를 사용해 nearest를 찾는다.
    let bestDen = baseDen;
    let bestDiff = Number.POSITIVE_INFINITY;
    for (const candDen of allowedDenByUnits) {
      const candUnits = 16 / candDen;
      const diff = Math.abs(candUnits - units);
      if (diff < bestDiff) {
        bestDiff = diff;
        bestDen = candDen;
      }
    }
    return bestDen;
  };

  const makeBeatContent = (b: AlphaTabBeat): string => {
    const lyricText = sanitizeBeatText(b.lyric);
    const chordText = sanitizeBeatText(b.chord);
    const composed = lyricText && chordText ? `${lyricText} ${chordText}` : lyricText ?? chordText;
    const beatText = sanitizeBeatText(composed);
    const playableNotes = (b.notes ?? []).filter((n) => Number(n.fret) >= 0);

    if (playableNotes.length === 0) {
      if (beatText) return `r{txt "${escapeTex(beatText)}"}`;
      return "r";
    }
    if (playableNotes.length === 1) {
      const n = playableNotes[0];
      const token = `${n.fret}.${n.string}`;
      if (beatText) return `${token}{txt "${escapeTex(beatText)}"}`;
      return token;
    }
    const tokens = playableNotes.map((n) => `${n.fret}.${n.string}`);
    if (beatText) tokens[0] = `${tokens[0]}{txt "${escapeTex(beatText)}"}`;
    return `(${tokens.join(" ")})`;
  };

  const prefixDurationChange = (denValue: number, content: string): string => {
    if (denValue === baseDen) return content;
    return `:${denValue} ${content}`;
  };

  const segments: Array<{ start: number; end: number; content: string }> = [];
  for (let i = 0; i < beats.length; i++) {
    const b = beats[i];
    const nextBeatTime = beats[i + 1]?.time ?? b.time + baseUnitSec;
    const playableNotes = (b.notes ?? []).filter((n) => Number(n.fret) >= 0);
    const noteEnd =
      playableNotes.length > 0
        ? Math.max(...playableNotes.map((n) => (Number.isFinite(n.end) ? n.end : nextBeatTime)))
        : nextBeatTime;

    const content = makeBeatContent(b);

    const segment1End = Math.min(noteEnd, nextBeatTime);
    if (segment1End > b.time + baseUnitSec * 0.05) {
      segments.push({ start: b.time, end: segment1End, content });
    }

    // note가 beat 경계 이전에 끝났고, 다음 beat까지 공백이 있다면 rest로 채운다.
    if (noteEnd + baseUnitSec * 0.05 < nextBeatTime) {
      segments.push({
        start: segment1End,
        end: nextBeatTime,
        content: "r",
      });
    }
  }

  const bars: string[] = [];
  let barTokens: string[] = [];
  let barUnits = 0;
  const pushBar = () => {
    // 바 길이가 모자라면 마지막에 기본 1/16 rest로 채운다.
    while (barUnits < measureUnitsTarget) {
      barTokens.push("r");
      barUnits += 1;
    }
    if (barTokens.length > 0) {
      if (!barTokens[0].trimStart().startsWith(":")) {
        barTokens[0] = `:${baseDen} ${barTokens[0]}`;
      }
      bars.push(`${barTokens.join(" ")} |`);
    }
    barTokens = [];
    barUnits = 0;
  };

  for (const seg of segments) {
    const durationSec = Math.max(0, seg.end - seg.start);
    const denValue = durationSecondsToDen(durationSec);
    const segUnits = 16 / denValue;

    // measure 단위 초과 시, 반올림 오차를 방지하기 위해 다음 bar로 넘긴다.
    if (barUnits + segUnits > measureUnitsTarget + 1e-6) {
      pushBar();
    }

    barTokens.push(prefixDurationChange(denValue, seg.content));
    barUnits += segUnits;
  }

  // 마지막 bar 마감
  if (barTokens.length > 0) pushBar();

  const barsPerRow = 4;
  const groupedRows: string[] = [];
  for (let i = 0; i < bars.length; i += barsPerRow) {
    groupedRows.push(bars.slice(i, i + barsPerRow).join(" "));
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

function formatDurationMs(milliseconds: number): string {
  let seconds = milliseconds / 1000;
  const minutes = (seconds / 60) | 0;
  seconds = (seconds - minutes * 60) | 0;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function getBeatPlaybackMs(beat: unknown): number | null {
  if (!beat || typeof beat !== "object") return null;
  return null;
}

function getBeatTick(beat: unknown): number | null {
  if (!beat || typeof beat !== "object") return null;
  const b = beat as {
    absolutePlaybackStart?: number;
    playbackStart?: number;
    playbackStartTick?: number;
    startTick?: number;
  };

  // Beat.playbackStart / absolutePlaybackStart는 midi tick 단위다.
  if (typeof b.absolutePlaybackStart === "number" && Number.isFinite(b.absolutePlaybackStart)) {
    return b.absolutePlaybackStart;
  }
  if (typeof b.playbackStart === "number" && Number.isFinite(b.playbackStart)) {
    return b.playbackStart;
  }
  if (typeof b.playbackStartTick === "number" && Number.isFinite(b.playbackStartTick)) {
    return b.playbackStartTick;
  }
  if (typeof b.startTick === "number" && Number.isFinite(b.startTick)) {
    return b.startTick;
  }
  return null;
}

function resolveMsFromTick(api: AlphaTabApiLike, tick: number): number | null {
  const endTick = Number(api.endTick ?? 0);
  const endTime = Number(api.endTime ?? 0);
  if (!Number.isFinite(tick) || endTick <= 0 || endTime <= 0) return null;
  const ratio = Math.max(0, Math.min(1, tick / endTick));
  return ratio * endTime;
}

function resolveRangeMsFromTickCache(
  api: AlphaTabApiLike,
  startTick: number,
  endTick: number,
): number | null {
  if (!api.tickCache) return null;
  const tickCache = api.tickCache;
  const trackIndexes = new Set(api.tracks.map((t) => t.index));

  if (!Number.isFinite(startTick) || !Number.isFinite(endTick) || startTick < 0 || endTick <= startTick) {
    return null;
  }

  let tick = startTick;
  let elapsedMs = 0;
  let steps = 0;

  // tickCache.findBeat는 입력 tick이 커서 구간을 포함하면 해당 beat의 duration을 준다.
  // 구간이 여러 beat을 걸치면 duration을 누적하여 range ms를 근사한다.
  while (tick < endTick && steps < 4096) {
    const lookup = tickCache.findBeat(trackIndexes, tick);
    if (!lookup) return null;

    const lookupStart = Number(lookup.start ?? tick);
    const lookupEnd = Number(
      lookup.end ?? (lookupStart + (lookup.tickDuration ?? 0)),
    );
    const tickDuration = Number(
      lookup.tickDuration ?? Math.max(0, lookupEnd - lookupStart),
    );
    const durationMs = Number(lookup.duration ?? NaN);

    if (!Number.isFinite(lookupStart) || !Number.isFinite(lookupEnd) || !Number.isFinite(durationMs) || tickDuration <= 0) {
      return null;
    }

    const nextTick = Math.min(lookupEnd, endTick);
    const partialTicks = Math.max(0, nextTick - tick);
    const ratio = Math.max(0, Math.min(1, partialTicks / tickDuration));
    elapsedMs += durationMs * ratio;

    tick = nextTick;
    steps++;
  }

  if (!Number.isFinite(elapsedMs)) return null;
  return elapsedMs;
}

function normalizeScoreForRendering(score: AlphaTabScore): AlphaTabScore | null {
  if (!score?.meta || !Array.isArray(score.tracks) || score.tracks.length === 0) return null;
  const track0 = score.tracks[0];
  if (!track0 || !Array.isArray(track0.beats)) return null;

  const rawBeats = track0.beats.map((b) => {
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

  const hasMillisLikeTimeline = rawBeats.some((b) => b.time > 3600);
  const timeScale = hasMillisLikeTimeline ? 0.001 : 1;
  const beats = rawBeats
    .map((b) => ({
      ...b,
      time: Math.max(0, b.time * timeScale),
      notes: b.notes.map((n) => ({
        ...n,
        start: n.start * timeScale,
        end: n.end * timeScale,
      })),
    }))
    .map((b) => ({
      ...b,
      notes: b.notes.slice(0, 4),
    }))
    .sort((a, b) => a.time - b.time)
    .slice(0, 2048);

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
