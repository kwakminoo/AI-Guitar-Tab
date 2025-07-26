from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import os
import tempfile
import shutil
from typing import Optional
import json

from audio_analyzer import AudioAnalyzer
from chord_extractor import ChordExtractor
from tab_generator import TabGenerator

app = FastAPI(title="AI Guitar Tab Generator", version="1.0.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 분석기 인스턴스
audio_analyzer = AudioAnalyzer()
chord_extractor = ChordExtractor()
tab_generator = TabGenerator()

@app.get("/")
async def root():
    return {"message": "AI Guitar Tab Generator API", "status": "running"}

@app.post("/analyze")
async def analyze_audio(
    file: UploadFile = File(...),
    key_change: Optional[int] = 0,  # 반음 단위로 키 변경
    capo_position: Optional[int] = 0,  # 카포 위치
    arpeggio_ratio: Optional[float] = 0.5  # 아르페지오 비율 (0.0 = 모두 스트로크, 1.0 = 모두 아르페지오)
):
    """
    음성/영상 파일을 분석하여 기타 타브 악보를 생성합니다.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 선택되지 않았습니다.")
    
    # 지원하는 파일 형식 확인
    supported_formats = ['.mp3', '.wav', '.m4a', '.mp4', '.avi', '.mov']
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    if file_extension not in supported_formats:
        raise HTTPException(
            status_code=400, 
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(supported_formats)}"
        )
    
    # 임시 파일로 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        shutil.copyfileobj(file.file, tmp_file)
        temp_path = tmp_file.name
    
    try:
        # 1. 오디오 분석 (키, 템포, 구조 등)
        audio_analysis = await audio_analyzer.analyze(temp_path)
        
        # 2. 코드 추출
        chords = await chord_extractor.extract_chords(temp_path, audio_analysis)
        
        # 3. 키 변경 적용
        if key_change != 0:
            chords = chord_extractor.transpose_chords(chords, key_change)
        
        # 4. 카포 적용
        if capo_position > 0:
            chords = chord_extractor.apply_capo(chords, capo_position)
        
        # 5. 타브 악보 생성
        tab_data = tab_generator.generate_tab(
            chords=chords,
            audio_analysis=audio_analysis,
            arpeggio_ratio=arpeggio_ratio
        )
        
        # 결과 반환
        result = {
            "success": True,
            "filename": file.filename,
            "analysis": {
                "key": audio_analysis.get("key", "C"),
                "tempo": audio_analysis.get("tempo", 120),
                "time_signature": audio_analysis.get("time_signature", "4/4"),
                "duration": audio_analysis.get("duration", 0),
                "key_change": key_change,
                "capo_position": capo_position,
                "arpeggio_ratio": arpeggio_ratio
            },
            "chords": chords,
            "tab": tab_data,
            "lyrics": audio_analysis.get("lyrics", []),
            "structure": audio_analysis.get("structure", [])
        }
        
        return JSONResponse(content=result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 중 오류가 발생했습니다: {str(e)}")
    
    finally:
        # 임시 파일 삭제
        if os.path.exists(temp_path):
            os.unlink(temp_path)

@app.post("/transpose")
async def transpose_chords(
    chords: list,
    semitones: int
):
    """
    코드를 주어진 반음 수만큼 이조합니다.
    """
    try:
        transposed = chord_extractor.transpose_chords(chords, semitones)
        return {"success": True, "chords": transposed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이조 중 오류가 발생했습니다: {str(e)}")

@app.post("/generate-tab")
async def generate_tab_only(
    chords: list,
    arpeggio_ratio: float = 0.5,
    tempo: int = 120,
    time_signature: str = "4/4"
):
    """
    기존 코드 데이터로부터 타브 악보만 재생성합니다.
    """
    try:
        audio_analysis = {
            "tempo": tempo,
            "time_signature": time_signature
        }
        
        tab_data = tab_generator.generate_tab(
            chords=chords,
            audio_analysis=audio_analysis,
            arpeggio_ratio=arpeggio_ratio
        )
        
        return {"success": True, "tab": tab_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"타브 생성 중 오류가 발생했습니다: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)