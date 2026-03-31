import type { AlphaTabScore } from "@/types/alphatabScore";

/** 빈 오선+타브용: 24마디(4/4) 휴지 */
export function createEmptyEditableScore(title = "빈 악보"): AlphaTabScore {
  const tempo = 90;
  const beatDur = 60 / tempo;
  const barCount = 24;
  const beatsPerBar = 4;
  const beatCount = barCount * beatsPerBar;
  return {
    version: 1,
    meta: {
      title,
      tempo,
      timeSignature: { numerator: 4, denominator: 4 },
      key: "C major",
      capo: 0,
    },
    tracks: [
      {
        name: "Guitar",
        type: "guitar",
        strings: 6,
        tuning: [64, 59, 55, 50, 45, 40],
        beats: Array.from({ length: beatCount }, (_, i) => ({
          time: i * beatDur,
          chord: null,
          lyric: null,
          notes: [],
        })),
      },
    ],
  };
}
