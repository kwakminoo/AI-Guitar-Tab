from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import librosa


@dataclass(frozen=True)
class ChordEvent:
    time: float
    chord: str


@dataclass(frozen=True)
class ChordAnalysisResult:
    key: str
    chords: List[ChordEvent]


class ChordAnalysisService:
    def __init__(self, frame_size_sec: float = 1.0):
        self.frame_size_sec = frame_size_sec

    def analyze_guitar_track(self, wav_path: Path) -> ChordAnalysisResult:
        if not wav_path.exists():
            raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {wav_path}")

        # 모노 로딩
        y, sr = librosa.load(str(wav_path), mono=True)

        # --- 전체 곡 Key 추정 (아주 단순한 크로마 기반) ---
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)

        # 12 반음에 대한 이름 (C, C#, D, ...)
        pitch_classes = np.array(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])

        # 메이저 / 마이너 키 프로파일 (Krumhansl-Kessler 스타일의 단순 버전)
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

        def best_key(chroma_vec: np.ndarray) -> str:
            chroma_vec = chroma_vec / (np.linalg.norm(chroma_vec) + 1e-9)
            best_score = -1e9
            best_name = "C major"
            for tonic in range(12):
                # 메이저
                mp = np.roll(major_profile, tonic)
                mp = mp / np.linalg.norm(mp)
                score_maj = float(np.dot(chroma_vec, mp))
                if score_maj > best_score:
                    best_score = score_maj
                    best_name = f"{pitch_classes[tonic]} major"

                # 마이너
                mn = np.roll(minor_profile, tonic)
                mn = mn / np.linalg.norm(mn)
                score_min = float(np.dot(chroma_vec, mn))
                if score_min > best_score:
                    best_score = score_min
                    best_name = f"{pitch_classes[tonic]} minor"

            return best_name

        full_key = best_key(chroma_mean)

        # --- 1초 단위 프레임별 코드 추정 (매우 단순한 triad 매칭) ---
        chords: List[ChordEvent] = []
        frame_samples = int(self.frame_size_sec * sr)
        n_frames = max(1, int(np.ceil(len(y) / frame_samples)))

        # triad 템플릿 (메이저/마이너)
        def triad_template(root_idx: int, is_major: bool) -> np.ndarray:
            # root, third, fifth
            third = (root_idx + (4 if is_major else 3)) % 12
            fifth = (root_idx + 7) % 12
            vec = np.zeros(12, dtype=float)
            vec[root_idx] = 1.0
            vec[third] = 0.8
            vec[fifth] = 0.9
            return vec

        triads = []
        for i in range(12):
            triads.append((f"{pitch_classes[i]}", triad_template(i, True)))   # major
            triads.append((f"{pitch_classes[i]}m", triad_template(i, False)))  # minor

        def chord_from_chroma(vec: np.ndarray) -> str:
            if np.allclose(vec, 0):
                return "N"
            v = vec / (np.linalg.norm(vec) + 1e-9)
            best_score = 0.0
            best_name = "N"
            for name, tmpl in triads:
                t = tmpl / (np.linalg.norm(tmpl) + 1e-9)
                score = float(np.dot(v, t))
                if score > best_score:
                    best_score = score
                    best_name = name
            # 스코어가 너무 낮으면 코드 없음으로 처리
            if best_score < 0.3:
                return "N"
            return best_name

        for idx in range(n_frames):
            start = idx * frame_samples
            end = min(len(y), (idx + 1) * frame_samples)
            frame = y[start:end]
            if len(frame) == 0:
                continue
            c = librosa.feature.chroma_cqt(y=frame, sr=sr).mean(axis=1)
            chord_label = chord_from_chroma(c)
            time_sec = idx * self.frame_size_sec
            chords.append(ChordEvent(time=time_sec, chord=chord_label))

        return ChordAnalysisResult(key=full_key, chords=chords)

