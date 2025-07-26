import librosa
import numpy as np
from typing import List, Dict, Tuple
import asyncio

class ChordExtractor:
    def __init__(self):
        # 기본 코드 템플릿 (크로마 벡터)
        self.chord_templates = self._create_chord_templates()
        self.chord_names = [
            'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B',
            'Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'A#m', 'Bm'
        ]
        
    def _create_chord_templates(self) -> np.ndarray:
        """
        주요 코드들의 크로마 템플릿을 생성합니다.
        """
        templates = []
        
        # 메이저 코드 (루트, 메이저 3도, 완전 5도)
        major_intervals = [0, 4, 7]
        # 마이너 코드 (루트, 마이너 3도, 완전 5도)
        minor_intervals = [0, 3, 7]
        
        # 12개 메이저 코드
        for root in range(12):
            template = np.zeros(12)
            for interval in major_intervals:
                template[(root + interval) % 12] = 1
            templates.append(template)
        
        # 12개 마이너 코드
        for root in range(12):
            template = np.zeros(12)
            for interval in minor_intervals:
                template[(root + interval) % 12] = 1
            templates.append(template)
        
        return np.array(templates)
    
    async def extract_chords(self, audio_path: str, audio_analysis: Dict) -> List[Dict]:
        """
        오디오에서 코드 진행을 추출합니다.
        """
        try:
            # 오디오 로드
            y, sr = librosa.load(audio_path, sr=22050)
            
            # 크로마그램 계산
            chromagram = librosa.feature.chroma_stft(
                y=y, sr=sr, hop_length=512, n_fft=2048
            )
            
            # 비트 정보
            tempo = audio_analysis.get('tempo', 120)
            beats = np.array(audio_analysis.get('beats', []))
            
            # 코드 인식
            chord_progression = await self._recognize_chords(chromagram, beats, sr)
            
            # 코드 정보에 타이밍 추가
            chord_sequence = self._create_chord_sequence(chord_progression, beats, sr, len(y))
            
            return chord_sequence
            
        except Exception as e:
            raise Exception(f"코드 추출 실패: {str(e)}")
    
    async def _recognize_chords(self, chromagram: np.ndarray, beats: np.ndarray, sr: int) -> List[str]:
        """
        크로마그램에서 코드를 인식합니다.
        """
        # 비트 단위로 크로마그램 평균화
        if len(beats) > 0:
            beat_chroma = []
            hop_length = 512
            
            for i in range(len(beats) - 1):
                start_frame = int(beats[i] * sr / hop_length)
                end_frame = int(beats[i + 1] * sr / hop_length)
                
                if end_frame > chromagram.shape[1]:
                    end_frame = chromagram.shape[1]
                
                if start_frame < end_frame:
                    segment_chroma = np.mean(chromagram[:, start_frame:end_frame], axis=1)
                    beat_chroma.append(segment_chroma)
            
            beat_chroma = np.array(beat_chroma).T
        else:
            # 비트 정보가 없으면 1초 단위로 분할
            beat_chroma = chromagram
        
        # 각 세그먼트에 대해 코드 인식
        chords = []
        for i in range(beat_chroma.shape[1]):
            chroma_vector = beat_chroma[:, i]
            
            # 각 코드 템플릿과의 유사도 계산
            similarities = []
            for template in self.chord_templates:
                # 코사인 유사도 계산
                similarity = np.dot(chroma_vector, template) / (
                    np.linalg.norm(chroma_vector) * np.linalg.norm(template) + 1e-8
                )
                similarities.append(similarity)
            
            # 가장 유사한 코드 선택
            best_chord_idx = np.argmax(similarities)
            chord_name = self.chord_names[best_chord_idx]
            
            # 유사도가 너무 낮으면 N.C. (No Chord)로 처리
            if similarities[best_chord_idx] < 0.3:
                chord_name = "N.C."
            
            chords.append(chord_name)
        
        # 연속된 같은 코드 병합
        merged_chords = []
        current_chord = None
        chord_count = 0
        
        for chord in chords:
            if chord == current_chord:
                chord_count += 1
            else:
                if current_chord is not None:
                    merged_chords.append((current_chord, chord_count))
                current_chord = chord
                chord_count = 1
        
        if current_chord is not None:
            merged_chords.append((current_chord, chord_count))
        
        # 짧은 코드들 필터링 (1비트 미만)
        filtered_chords = []
        for chord, count in merged_chords:
            if count >= 1 or chord != "N.C.":
                filtered_chords.extend([chord] * count)
        
        return filtered_chords
    
    def _create_chord_sequence(self, chords: List[str], beats: np.ndarray, sr: int, audio_length: int) -> List[Dict]:
        """
        코드 리스트를 타이밍 정보와 함께 시퀀스로 변환합니다.
        """
        chord_sequence = []
        
        if len(beats) == 0:
            # 비트 정보가 없으면 균등 분할
            duration_per_chord = (audio_length / sr) / len(chords) if chords else 1.0
            
            for i, chord in enumerate(chords):
                start_time = i * duration_per_chord
                end_time = (i + 1) * duration_per_chord
                
                chord_sequence.append({
                    "chord": chord,
                    "start_time": float(start_time),
                    "end_time": float(end_time),
                    "duration": float(duration_per_chord),
                    "beat": i + 1
                })
        else:
            # 비트 정보를 사용
            beats_per_chord = max(1, len(beats) // len(chords)) if chords else 1
            
            for i, chord in enumerate(chords):
                beat_start = i * beats_per_chord
                beat_end = min((i + 1) * beats_per_chord, len(beats) - 1)
                
                start_time = beats[beat_start] if beat_start < len(beats) else 0
                end_time = beats[beat_end] if beat_end < len(beats) else beats[-1]
                
                chord_sequence.append({
                    "chord": chord,
                    "start_time": float(start_time),
                    "end_time": float(end_time),
                    "duration": float(end_time - start_time),
                    "beat": beat_start + 1
                })
        
        return chord_sequence
    
    def transpose_chords(self, chords: List[Dict], semitones: int) -> List[Dict]:
        """
        코드를 주어진 반음 수만큼 이조합니다.
        """
        transposed_chords = []
        
        for chord_info in chords:
            original_chord = chord_info["chord"]
            
            if original_chord == "N.C.":
                transposed_chord = original_chord
            else:
                transposed_chord = self._transpose_single_chord(original_chord, semitones)
            
            new_chord_info = chord_info.copy()
            new_chord_info["chord"] = transposed_chord
            new_chord_info["original_chord"] = original_chord
            
            transposed_chords.append(new_chord_info)
        
        return transposed_chords
    
    def _transpose_single_chord(self, chord: str, semitones: int) -> str:
        """
        단일 코드를 이조합니다.
        """
        # 코드 파싱
        root, quality = self._parse_chord(chord)
        
        if root is None:
            return chord
        
        # 루트 노트 이조
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        try:
            root_index = note_names.index(root)
            new_root_index = (root_index + semitones) % 12
            new_root = note_names[new_root_index]
            
            return new_root + quality
        except ValueError:
            return chord
    
    def _parse_chord(self, chord: str) -> Tuple[str, str]:
        """
        코드 문자열을 루트와 품질로 파싱합니다.
        """
        if not chord or chord == "N.C.":
            return None, ""
        
        # 샵/플랫 처리
        if len(chord) > 1 and chord[1] in ['#', 'b']:
            root = chord[:2]
            quality = chord[2:]
        else:
            root = chord[0]
            quality = chord[1:]
        
        # 플랫을 샵으로 변환
        flat_to_sharp = {
            'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'
        }
        
        if root in flat_to_sharp:
            root = flat_to_sharp[root]
        
        return root, quality
    
    def apply_capo(self, chords: List[Dict], capo_position: int) -> List[Dict]:
        """
        카포 위치를 적용하여 코드를 변환합니다.
        """
        if capo_position == 0:
            return chords
        
        # 카포는 실제로는 이조와 반대 방향
        return self.transpose_chords(chords, -capo_position)