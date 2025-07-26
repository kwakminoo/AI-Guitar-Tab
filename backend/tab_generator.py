import json
from typing import List, Dict, Tuple
import random

class TabGenerator:
    def __init__(self):
        # 기본 기타 코드 포지션 (6번줄부터 1번줄까지)
        self.chord_positions = {
            # 메이저 코드
            'C': [None, 3, 2, 0, 1, 0],
            'D': [None, None, 0, 2, 3, 2],
            'E': [0, 2, 2, 1, 0, 0],
            'F': [1, 3, 3, 2, 1, 1],
            'G': [3, 2, 0, 0, 3, 3],
            'A': [None, 0, 2, 2, 2, 0],
            'B': [None, 2, 4, 4, 4, 2],
            
            # 샵 메이저 코드
            'C#': [None, 4, 3, 1, 2, 1],
            'D#': [None, None, 1, 3, 4, 3],
            'F#': [2, 4, 4, 3, 2, 2],
            'G#': [4, 6, 6, 5, 4, 4],
            'A#': [None, 1, 3, 3, 3, 1],
            
            # 마이너 코드
            'Cm': [None, 3, 5, 5, 4, 3],
            'Dm': [None, None, 0, 2, 3, 1],
            'Em': [0, 2, 2, 0, 0, 0],
            'Fm': [1, 3, 3, 1, 1, 1],
            'Gm': [3, 5, 5, 3, 3, 3],
            'Am': [None, 0, 2, 2, 1, 0],
            'Bm': [None, 2, 4, 4, 3, 2],
            
            # 샵 마이너 코드
            'C#m': [None, 4, 6, 6, 5, 4],
            'D#m': [None, None, 1, 3, 4, 2],
            'F#m': [2, 4, 4, 2, 2, 2],
            'G#m': [4, 6, 6, 4, 4, 4],
            'A#m': [None, 1, 3, 3, 2, 1],
        }
        
        # 아르페지오 패턴들
        self.arpeggio_patterns = [
            [6, 4, 3, 2, 3, 4],  # 기본 아르페지오
            [6, 3, 2, 3, 4, 3],  # 변형 1
            [6, 4, 2, 4, 3, 4],  # 변형 2
            [6, 5, 4, 3, 2, 1],  # 하행 아르페지오
        ]
        
        # 스트로크 패턴들
        self.strum_patterns = [
            ['D', 'D', 'U', 'D', 'U'],  # 기본 스트로크
            ['D', 'D', 'U', 'D', 'D', 'U'],  # 변형 1
            ['D', 'U', 'D', 'U'],  # 간단한 패턴
            ['D', 'D', 'U', 'U', 'D', 'U'],  # 복잡한 패턴
        ]
    
    def generate_tab(self, chords: List[Dict], audio_analysis: Dict, arpeggio_ratio: float = 0.5) -> Dict:
        """
        코드 진행으로부터 기타 타브 악보를 생성합니다.
        """
        try:
            tempo = audio_analysis.get('tempo', 120)
            time_signature = audio_analysis.get('time_signature', '4/4')
            
            # 타브 데이터 초기화
            tab_data = {
                "tempo": tempo,
                "time_signature": time_signature,
                "measures": [],
                "chord_diagrams": {},
                "playing_style": {
                    "arpeggio_ratio": arpeggio_ratio,
                    "patterns_used": []
                }
            }
            
            # 각 코드에 대한 다이어그램 생성
            for chord_info in chords:
                chord_name = chord_info["chord"]
                if chord_name not in tab_data["chord_diagrams"] and chord_name != "N.C.":
                    tab_data["chord_diagrams"][chord_name] = self._get_chord_diagram(chord_name)
            
            # 마디별 타브 생성
            measures = self._create_measures(chords, arpeggio_ratio, tempo)
            tab_data["measures"] = measures
            
            return tab_data
            
        except Exception as e:
            raise Exception(f"타브 생성 실패: {str(e)}")
    
    def _get_chord_diagram(self, chord_name: str) -> Dict:
        """
        코드 다이어그램 정보를 반환합니다.
        """
        if chord_name in self.chord_positions:
            positions = self.chord_positions[chord_name]
        else:
            # 알 수 없는 코드의 경우 기본값
            positions = [None, None, None, None, None, None]
        
        return {
            "name": chord_name,
            "positions": positions,  # [6번줄, 5번줄, 4번줄, 3번줄, 2번줄, 1번줄]
            "fingers": self._suggest_fingering(positions),
            "difficulty": self._calculate_difficulty(positions)
        }
    
    def _suggest_fingering(self, positions: List) -> List:
        """
        코드 포지션에 대한 핑거링을 제안합니다.
        """
        fingering = [None] * 6
        
        # 간단한 핑거링 알고리즘
        used_fingers = []
        frets = [pos for pos in positions if pos is not None and pos > 0]
        
        if frets:
            sorted_frets = sorted(enumerate(frets), key=lambda x: x[1])
            
            finger_map = [1, 2, 3, 4]  # 검지, 중지, 약지, 새끼
            
            for i, (string_idx, fret) in enumerate(sorted_frets):
                if i < len(finger_map):
                    # 해당 줄의 원래 인덱스 찾기
                    original_idx = next(j for j, pos in enumerate(positions) if pos == fret)
                    fingering[original_idx] = finger_map[i]
        
        return fingering
    
    def _calculate_difficulty(self, positions: List) -> int:
        """
        코드의 난이도를 계산합니다 (1-5).
        """
        if not any(pos for pos in positions if pos is not None):
            return 1  # 오픈 코드
        
        frets = [pos for pos in positions if pos is not None and pos > 0]
        
        if not frets:
            return 1
        
        # 프렛 범위
        fret_range = max(frets) - min(frets) if frets else 0
        
        # 바레 코드 확인
        is_barre = len(set(frets)) < len(frets)
        
        # 높은 프렛 사용
        high_frets = any(fret > 5 for fret in frets)
        
        difficulty = 1
        if fret_range > 3:
            difficulty += 1
        if is_barre:
            difficulty += 1
        if high_frets:
            difficulty += 1
        if len(frets) > 4:
            difficulty += 1
        
        return min(difficulty, 5)
    
    def _create_measures(self, chords: List[Dict], arpeggio_ratio: float, tempo: int) -> List[Dict]:
        """
        코드 진행으로부터 마디를 생성합니다.
        """
        measures = []
        current_measure = {
            "measure_number": 1,
            "chords": [],
            "tab_notation": [],
            "timing": []
        }
        
        beats_per_measure = 4  # 4/4박자 기준
        current_beat = 0
        
        for chord_info in chords:
            chord_name = chord_info["chord"]
            duration = chord_info.get("duration", 1.0)
            
            # 연주 스타일 결정 (아르페지오 vs 스트로크)
            is_arpeggio = random.random() < arpeggio_ratio
            
            # 타브 노테이션 생성
            if chord_name == "N.C.":
                notation = self._create_rest_notation(duration)
            elif is_arpeggio:
                notation = self._create_arpeggio_notation(chord_name, duration)
            else:
                notation = self._create_strum_notation(chord_name, duration)
            
            chord_data = {
                "chord": chord_name,
                "duration": duration,
                "style": "arpeggio" if is_arpeggio else "strum",
                "start_beat": current_beat + 1
            }
            
            current_measure["chords"].append(chord_data)
            current_measure["tab_notation"].extend(notation)
            current_measure["timing"].append({
                "beat": current_beat + 1,
                "duration": duration,
                "type": "arpeggio" if is_arpeggio else "strum"
            })
            
            current_beat += duration
            
            # 마디가 완성되면 새 마디 시작
            if current_beat >= beats_per_measure:
                measures.append(current_measure)
                current_measure = {
                    "measure_number": len(measures) + 1,
                    "chords": [],
                    "tab_notation": [],
                    "timing": []
                }
                current_beat = current_beat - beats_per_measure
        
        # 마지막 마디 추가
        if current_measure["chords"]:
            measures.append(current_measure)
        
        return measures
    
    def _create_arpeggio_notation(self, chord_name: str, duration: float) -> List[Dict]:
        """
        아르페지오 타브 노테이션을 생성합니다.
        """
        if chord_name not in self.chord_positions:
            return []
        
        positions = self.chord_positions[chord_name]
        pattern = random.choice(self.arpeggio_patterns)
        
        notation = []
        notes_per_beat = max(1, int(4 * duration))  # duration에 따른 노트 수
        
        for i in range(notes_per_beat):
            string_num = pattern[i % len(pattern)]
            string_idx = string_num - 1  # 0-based 인덱스
            
            if string_idx < len(positions) and positions[string_idx] is not None:
                fret = positions[string_idx]
                
                notation.append({
                    "string": string_num,
                    "fret": fret,
                    "timing": i / notes_per_beat,
                    "duration": 1 / notes_per_beat,
                    "technique": "pick"
                })
        
        return notation
    
    def _create_strum_notation(self, chord_name: str, duration: float) -> List[Dict]:
        """
        스트로크 타브 노테이션을 생성합니다.
        """
        if chord_name not in self.chord_positions:
            return []
        
        positions = self.chord_positions[chord_name]
        pattern = random.choice(self.strum_patterns)
        
        notation = []
        strums_per_beat = len(pattern)
        strum_duration = duration / strums_per_beat
        
        for i, direction in enumerate(pattern):
            strum_data = {
                "type": "strum",
                "direction": direction,  # 'D' for down, 'U' for up
                "timing": i * strum_duration,
                "duration": strum_duration,
                "strings": []
            }
            
            # 스트로크에 포함될 줄들
            for string_num in range(1, 7):
                string_idx = string_num - 1
                if string_idx < len(positions) and positions[string_idx] is not None:
                    strum_data["strings"].append({
                        "string": string_num,
                        "fret": positions[string_idx]
                    })
            
            notation.append(strum_data)
        
        return notation
    
    def _create_rest_notation(self, duration: float) -> List[Dict]:
        """
        쉼표 노테이션을 생성합니다.
        """
        return [{
            "type": "rest",
            "duration": duration,
            "timing": 0
        }]