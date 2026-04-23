export type AlphaTabNote = {
  string: number;
  fret: number;
  start: number;
  end: number;
};

export type AlphaTabBeat = {
  time: number;
  chord: string | null;
  lyric: string | null;
  notes: AlphaTabNote[];
};

export type AlphaTabTrack = {
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
    /** 백엔드가 채울 수 있음 (LRCLIB 등) */
    artist?: string;
    lyrics?: string | null;
    tempo: number;
    timeSignature: { numerator: number; denominator: number };
    key: string;
    capo: number;
    capoMethod?: string;
    capoCandidateRange?: [number, number];
    chords?: string[];
  };
  tracks: AlphaTabTrack[];
};
