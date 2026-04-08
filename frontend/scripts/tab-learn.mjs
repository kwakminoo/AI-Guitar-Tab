/**
 * test-scores 정답 .atex vs 웹 생성 tab/guitar.alphatex + midi/guitar.mid 비교 학습.
 * 산출: scripts/tab-learning-out/measure_diff.csv, learned_rules.json, TAB_LEARNING_REPORT.md
 * (AlphaTex는 Node에서 @coderline/alphatab 전체 파서를 쓰기 어려워 헤더·마디·{ch}는 정규식으로 추출)
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from "fs";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(__dirname, "..");
const REPO_ROOT = resolve(FRONTEND_ROOT, "..");
const CONFIG_PATH = join(__dirname, "test-score-pairs.json");
const OUT_DIR = join(__dirname, "tab-learning-out");

const BASE = {
  C: 0,
  "C#": 1,
  Db: 1,
  D: 2,
  "D#": 3,
  Eb: 3,
  E: 4,
  F: 5,
  "F#": 6,
  Gb: 6,
  G: 7,
  "G#": 8,
  Ab: 8,
  A: 9,
  "A#": 10,
  Bb: 10,
  B: 11,
};

/**
 * @param {string} name
 * @returns {number | null} pitch class 0-11
 */
function parseChordRoot(name) {
  const s = String(name).trim();
  const m = s.match(/^([A-G])(#|b|##|bb)?/i);
  if (!m) return null;
  const letter = m[1].toUpperCase();
  let acc = m[2] || "";
  const key = letter + (acc === "##" || acc === "bb" ? acc : acc === "#" || acc === "b" ? acc : "");
  let pc = BASE[key];
  if (pc === undefined) {
    pc = BASE[letter];
  }
  if (pc === undefined) return null;
  if (acc === "##") pc = (pc + 2) % 12;
  else if (acc === "bb") pc = (pc - 2 + 12) % 12;
  return pc;
}

/**
 * @param {string} tex
 * @returns {number}
 */
function extractCapo(tex) {
  const m = tex.match(/\\capo\s+(\d{1,2})\b/i);
  return m ? Math.min(12, Math.max(0, parseInt(m[1], 10))) : 0;
}

/**
 * @param {string} tex
 * @returns {number | null}
 */
function extractTempo(tex) {
  const m = tex.match(/\\tempo\s+(\d+(?:\.\d+)?)/i);
  return m ? parseFloat(m[1]) : null;
}

/**
 * @param {string} tex
 */
function extractBars(tex) {
  const lines = tex.split(/\r?\n/);
  let i = 0;
  for (; i < lines.length; i++) {
    if (/^\s*:\d+/.test(lines[i])) break;
  }
  if (i >= lines.length) {
    const joined = lines.join("\n");
    return joined.split("|").map((b) => b.trim()).filter(Boolean);
  }
  const body = lines.slice(i).join("\n");
  return body.split("|").map((b) => b.trim()).filter(Boolean);
}

/**
 * @param {string} barText
 * @returns {string[]}
 */
function chordNamesInBar(barText) {
  const names = [];
  const re = /\{ch\s+"([^"]*)"\}/g;
  let m;
  while ((m = re.exec(barText)) !== null) {
    names.push(m[1]);
  }
  return names;
}

/**
 * @param {string} barText
 * @returns {number}
 */
function countDyMarks(barText) {
  const re = /\{dy\s+[^}]+\}/g;
  const m = barText.match(re);
  return m ? m.length : 0;
}

/**
 * 첫 코드의 울림 높이 피치클래스 (카포는 너트를 올린 만큼 반음 상향).
 * @param {string[]} names
 * @param {number} capo
 */
function firstSoundingPc(names, capo) {
  for (const n of names) {
    const pc = parseChordRoot(n);
    if (pc === null) continue;
    return (pc + capo) % 12;
  }
  return null;
}

/**
 * @param {string} dir
 * @returns {string}
 */
function discoverJobFolder(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const jobs = [];
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const p = join(dir, e.name);
    const mid = join(p, "midi", "guitar.mid");
    const tab = join(p, "tab", "guitar.alphatex");
    if (existsSync(mid) && existsSync(tab)) jobs.push(e.name);
  }
  if (jobs.length === 0) throw new Error(`job 폴더 없음: ${dir}`);
  if (jobs.length > 1)
    throw new Error(`job 폴더가 여러 개입니다. 하나만 두거나 설정에 지정하세요: ${dir} → ${jobs.join(", ")}`);
  return join(dir, jobs[0]);
}

/**
 * @param {string} p
 * @returns {any | null}
 */
function readJsonSafe(p) {
  try {
    if (!existsSync(p)) return null;
    return JSON.parse(readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}

/**
 * @param {string} midiPath
 * @param {string} jobMetaPath
 */
function runMidiFeatures(midiPath, jobMetaPath) {
  const script = join(REPO_ROOT, "backend", "scripts", "tab_learn_midi.py");
  const opts = { encoding: "utf8", cwd: REPO_ROOT, maxBuffer: 32 * 1024 * 1024 };
  let r = spawnSync("python", [script, midiPath, jobMetaPath], opts);
  if (r.status !== 0 || !r.stdout) {
    r = spawnSync("py", ["-3", script, midiPath, jobMetaPath], opts);
  }
  if (r.status !== 0) {
    throw new Error(
      `midi 분석 실패: ${r.stderr || r.stdout || "python 오류"}\n` +
        `pretty_midi가 backend venv에 설치되어 있는지 확인하세요.`
    );
  }
  return JSON.parse(r.stdout);
}

/**
 * @param {any} row
 */
function csvEscape(row) {
  return row.map((c) => {
    const s = String(c ?? "");
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  });
}

function main() {
  const cfg = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
  const testRoot = join(FRONTEND_ROOT, cfg.testScoresRoot.replace(/\//g, "\\"));

  mkdirSync(OUT_DIR, { recursive: true });

  const csvRows = [
    [
      "songId",
      "barIndex",
      "refFirstChord",
      "genFirstChord",
      "refSoundingPc",
      "genSoundingPc",
      "chordMatch",
      "midiTopPcs",
      "refCapo",
      "genCapo",
      "notes",
    ].join(","),
  ];

  const perSong = [];
  const hints = new Set();

  for (const pair of cfg.pairs) {
    const songDir = join(testRoot, pair.songFolder);
    if (!existsSync(songDir)) {
      console.warn(`건너뜀(폴더 없음): ${pair.songFolder}`);
      continue;
    }

    const refPath = join(songDir, pair.refAtex);
    const genJobDir = discoverJobFolder(songDir);
    const genPath = join(genJobDir, "tab", "guitar.alphatex");
    const midiPath = join(genJobDir, "midi", "guitar.mid");
    const jobMetaPath = join(genJobDir, "job_meta.json");
    const summaryPath = join(genJobDir, "tab", "summary.json");

    const refTex = readFileSync(refPath, "utf8");
    const genTex = readFileSync(genPath, "utf8");
    const summary = readJsonSafe(summaryPath);

    const refCapo = extractCapo(refTex);
    let genCapo = extractCapo(genTex);
    if (genCapo === 0 && summary && typeof summary.capo_guess === "number") {
      genCapo = summary.capo_guess;
    }

    const refTempo = extractTempo(refTex);
    const genTempo = extractTempo(genTex);

    const refBars = extractBars(refTex);
    const genBars = extractBars(genTex);

    let midiFeat = null;
    try {
      midiFeat = runMidiFeatures(midiPath, jobMetaPath);
    } catch (e) {
      console.warn(String(e.message));
      hints.add("MIDI 분석 스크립트 실행 실패 — backend 의존성(pretty_midi) 확인");
    }

    const midiBarCount = midiFeat ? midiFeat.barCount : 0;
    const effectiveN =
      midiBarCount > 0
        ? Math.min(refBars.length, genBars.length, midiBarCount)
        : Math.min(refBars.length, genBars.length);

    let matches = 0;
    let compared = 0;

    for (let bi = 0; bi < effectiveN; bi++) {
      const rChords = chordNamesInBar(refBars[bi] || "");
      const gChords = chordNamesInBar(genBars[bi] || "");
      const rPc = firstSoundingPc(rChords, refCapo);
      const gPc = firstSoundingPc(gChords, genCapo);
      let chordMatch = "";
      if (rPc !== null && gPc !== null) {
        compared++;
        if (rPc === gPc) {
          matches++;
          chordMatch = "1";
        } else {
          chordMatch = "0";
        }
      } else {
        chordMatch = "";
      }

      let midiTop = "";
      if (midiFeat && midiFeat.bars && midiFeat.bars[bi]) {
        midiTop = (midiFeat.bars[bi].topPitchClasses || []).join(";");
      }

      const notes =
        refBars.length !== genBars.length
          ? `refBars=${refBars.length} genBars=${genBars.length}`
          : midiBarCount && midiBarCount < effectiveN
            ? `midiBars=${midiBarCount}`
            : "";

      csvRows.push(
        csvEscape([
          pair.id,
          bi,
          rChords[0] || "",
          gChords[0] || "",
          rPc !== null ? String(rPc) : "",
          gPc !== null ? String(gPc) : "",
          chordMatch,
          midiTop,
          refCapo,
          genCapo,
          notes,
        ]).join(",")
      );
    }

    const dyTotal = genBars.reduce((acc, b) => acc + countDyMarks(b), 0);
    const chordBarMatchRate = compared > 0 ? matches / compared : 0;

    if (refCapo !== genCapo) {
      hints.add("카포: 정답과 생성 capo가 자주 다름 → 제목/가사 외 MIDI·정답 기반 capo 추정 검토");
    }
    if (refBars.length !== genBars.length) {
      hints.add("마디 수: 정답 악보와 생성물 마디 분할(|) 수가 다름 → 리듬 양자화·온셋 스냅 파라미터 검토");
    }
    if (dyTotal > 50) {
      hints.add("주법: 생성물에 {dy} 다이내믹 표기가 많음 → ref 스타일(생략) 옵션 검토");
    }

    perSong.push({
      id: pair.id,
      songFolder: pair.songFolder,
      refCapo,
      genCapo,
      refTempo,
      genTempo,
      barCounts: {
        ref: refBars.length,
        gen: genBars.length,
        midi: midiBarCount,
      },
      chordBarMatchRate: Math.round(chordBarMatchRate * 1000) / 1000,
      comparedBars: compared,
      dyMarkCountGen: dyTotal,
      jobFolder: genJobDir.replace(FRONTEND_ROOT + "\\", "").replace(/\\/g, "/"),
    });
  }

  const meanChord =
    perSong.length > 0
      ? perSong.reduce((a, s) => a + s.chordBarMatchRate, 0) / perSong.length
      : 0;
  const capoMismatch = perSong.filter((s) => s.refCapo !== s.genCapo).length;

  const learned = {
    version: 1,
    generatedAt: new Date().toISOString(),
    pairCount: perSong.length,
    perSong,
    aggregate: {
      meanChordBarMatchRate: Math.round(meanChord * 1000) / 1000,
      capoMismatchCount: capoMismatch,
      hints: [...hints],
    },
  };

  writeFileSync(join(OUT_DIR, "learned_rules.json"), JSON.stringify(learned, null, 2), "utf8");
  writeFileSync(join(OUT_DIR, "measure_diff.csv"), csvRows.join("\n"), "utf8");

  const md = [
    "# TAB 학습 리포트 (test-scores 8곡)",
    "",
    `- 생성 시각: ${learned.generatedAt}`,
    `- 평균 첫 코드 울림 일치율(마디별): **${learned.aggregate.meanChordBarMatchRate}**`,
    `- 카포 불일치 곡 수: **${capoMismatch} / ${perSong.length}**`,
    "",
    "## 목표",
    "",
    "웹 파이프라인이 생성한 `guitar.alphatex`가 정답 `.atex`와 같은 **코드(울림 높이)**, **카포**, **주법 밀도**에 가깝도록 하기 위한 오프라인 지표입니다.",
    "",
    "## 한계",
    "",
    "- 마디는 `|`로만 나누며, 정답·생성·MIDI의 **마디 수가 다르면** 앞 구간만 비교합니다.",
    "- MIDI 마디는 `job_meta.json`의 `beat_times_sec`와 4/4(또는 MIDI 박자) 기준입니다.",
    "- 스템 오디오와 합성 음의 유사도는 포함하지 않습니다(후속 단계).",
    "",
    "## 곡별 요약",
    "",
    "| id | 카포(ref/gen) | 마디 수 ref/gen/MIDI | 코드 일치율 | 생성 {dy} 개수 |",
    "|---|---:|---:|---:|---:|",
    ...perSong.map(
      (s) =>
        `| ${s.id} | ${s.refCapo}/${s.genCapo} | ${s.barCounts.ref}/${s.barCounts.gen}/${s.barCounts.midi} | ${s.chordBarMatchRate} | ${s.dyMarkCountGen} |`
    ),
    "",
    "## 파이프라인 우선순위 힌트",
    "",
    ...learned.aggregate.hints.map((h) => `- ${h}`),
    "",
    "## 산출물",
    "",
    "- `measure_diff.csv` — 마디별 첫 코드·울림 PC·MIDI 상위 피치클래스",
    "- `learned_rules.json` — 집계 JSON",
    "",
  ].join("\n");

  writeFileSync(join(OUT_DIR, "TAB_LEARNING_REPORT.md"), md, "utf8");

  console.log(`완료: ${OUT_DIR}`);
  console.log(`  learned_rules.json, measure_diff.csv, TAB_LEARNING_REPORT.md`);
}

main();
