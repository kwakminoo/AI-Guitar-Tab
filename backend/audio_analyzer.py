import librosa
import numpy as np
import asyncio
from typing import Dict, List, Tuple
import tempfile
import os
from pydub import AudioSegment
import subprocess
import json

class AudioAnalyzer:
    def __init__(self):
        self.sample_rate = 22050
        self.hop_length = 512
        self.frame_length = 2048
        
    async def analyze(self, file_path: str) -> Dict:
        """
        오디오 파일을 분석하여 음악적 특성을 추출합니다.
        """
        try:
            # 비디오 파일인 경우 오디오 추출
            audio_path = await self._extract_audio_if_video(file_path)
            
            # 오디오 로드
            y, sr = librosa.load(audio_path, sr=self.sample_rate)
            
            # 기본 분석
            duration = librosa.get_duration(y=y, sr=sr)
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
            
            # 키 추정
            key = await self._estimate_key(y, sr)
            
            # 코드 진행 분석을 위한 크로마그램
            chromagram = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=self.hop_length)
            
            # 곡 구조 분석 (간단한 버전)
            structure = await self._analyze_structure(y, sr, beats)
            
            # 음량 분석
            rms = librosa.feature.rms(y=y, hop_length=self.hop_length)[0]
            
            # 결과 반환
            analysis = {
                "duration": float(duration),
                "tempo": float(tempo),
                "key": key,
                "time_signature": "4/4",  # 기본값, 향후 개선 필요
                "chromagram": chromagram.tolist(),
                "beats": beats.tolist(),
                "structure": structure,
                "rms": rms.tolist(),
                "sample_rate": sr,
                "lyrics": []  # 가사 인식은 향후 구현
            }
            
            # 임시 파일 정리
            if audio_path != file_path:
                os.unlink(audio_path)
            
            return analysis
            
        except Exception as e:
            raise Exception(f"오디오 분석 실패: {str(e)}")
    
    async def _extract_audio_if_video(self, file_path: str) -> str:
        """
        비디오 파일인 경우 오디오를 추출합니다.
        """
        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension in video_extensions:
            # FFmpeg을 사용하여 오디오 추출
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_audio:
                audio_path = tmp_audio.name
            
            try:
                # FFmpeg 명령어로 오디오 추출
                cmd = [
                    'ffmpeg', '-i', file_path, 
                    '-ac', '1',  # 모노
                    '-ar', str(self.sample_rate),  # 샘플레이트
                    '-y',  # 덮어쓰기
                    audio_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg 오류: {result.stderr}")
                
                return audio_path
                
            except FileNotFoundError:
                # FFmpeg이 없는 경우 pydub 사용
                audio = AudioSegment.from_file(file_path)
                audio = audio.set_channels(1)  # 모노로 변환
                audio = audio.set_frame_rate(self.sample_rate)
                audio.export(audio_path, format="wav")
                return audio_path
        
        return file_path
    
    async def _estimate_key(self, y: np.ndarray, sr: int) -> str:
        """
        크로마 특성을 사용하여 키를 추정합니다.
        """
        # 크로마그램 계산
        chromagram = librosa.feature.chroma_stft(y=y, sr=sr)
        
        # 각 키에 대한 크로마 프로파일 (Krumhansl-Schmuckler 알고리즘 기반)
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        
        # 평균 크로마 벡터
        chroma_mean = np.mean(chromagram, axis=1)
        
        # 각 키와의 상관관계 계산
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        correlations = []
        
        for i in range(12):
            # 메이저 키
            major_shifted = np.roll(major_profile, i)
            major_corr = np.corrcoef(chroma_mean, major_shifted)[0, 1]
            correlations.append((key_names[i], major_corr, 'major'))
            
            # 마이너 키
            minor_shifted = np.roll(minor_profile, i)
            minor_corr = np.corrcoef(chroma_mean, minor_shifted)[0, 1]
            correlations.append((key_names[i] + 'm', minor_corr, 'minor'))
        
        # 가장 높은 상관관계를 가진 키 선택
        best_key = max(correlations, key=lambda x: x[1] if not np.isnan(x[1]) else -1)
        
        return best_key[0] if not np.isnan(best_key[1]) else 'C'
    
    async def _analyze_structure(self, y: np.ndarray, sr: int, beats: np.ndarray) -> List[Dict]:
        """
        곡의 구조를 분석합니다 (인트로, 벌스, 코러스 등).
        """
        duration = librosa.get_duration(y=y, sr=sr)
        
        # 간단한 구조 분석 (향후 개선 필요)
        structure = []
        
        # 8마디 단위로 구간 나누기 (임시)
        measures_per_section = 8
        beat_duration = 60.0 / (len(beats) / duration * 4)  # 1비트당 시간
        section_duration = measures_per_section * 4 * beat_duration
        
        section_types = ['intro', 'verse', 'chorus', 'verse', 'chorus', 'bridge', 'chorus', 'outro']
        
        for i, section_type in enumerate(section_types):
            start_time = i * section_duration
            end_time = min((i + 1) * section_duration, duration)
            
            if start_time >= duration:
                break
                
            structure.append({
                "section": section_type,
                "start_time": float(start_time),
                "end_time": float(end_time),
                "measures": measures_per_section
            })
        
        return structure