import React, { useState } from 'react';
import './index.css';

// 컴포넌트 임포트
import Header from './components/Header';
import FileUpload from './components/FileUpload';
import ControlPanel from './components/ControlPanel';
import TabDisplay from './components/TabDisplay';
import ChordChart from './components/ChordChart';
import LoadingSpinner from './components/LoadingSpinner';
import ErrorMessage from './components/ErrorMessage';

// API 서비스
import { analyzeAudio } from './services/api';

function App() {
  // 상태 관리
  const [analysisResult, setAnalysisResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [uploadedFile, setUploadedFile] = useState(null);
  
  // 컨트롤 상태
  const [keyChange, setKeyChange] = useState(0);
  const [capoPosition, setCapoPosition] = useState(0);
  const [arpeggioRatio, setArpeggioRatio] = useState(0.5);

  // 파일 업로드 및 분석
  const handleFileUpload = async (file) => {
    setIsLoading(true);
    setError(null);
    setUploadedFile(file);

    try {
      const result = await analyzeAudio(file, {
        keyChange,
        capoPosition,
        arpeggioRatio
      });

      setAnalysisResult(result);
    } catch (err) {
      setError(err.message || '파일 분석 중 오류가 발생했습니다.');
      console.error('Analysis error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 설정 변경 및 재분석
  const handleSettingsChange = async (newSettings) => {
    if (!uploadedFile) return;

    setKeyChange(newSettings.keyChange);
    setCapoPosition(newSettings.capoPosition);
    setArpeggioRatio(newSettings.arpeggioRatio);

    setIsLoading(true);
    setError(null);

    try {
      const result = await analyzeAudio(uploadedFile, newSettings);
      setAnalysisResult(result);
    } catch (err) {
      setError(err.message || '재분석 중 오류가 발생했습니다.');
      console.error('Re-analysis error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 에러 초기화
  const clearError = () => {
    setError(null);
  };

  // 결과 초기화
  const clearResults = () => {
    setAnalysisResult(null);
    setUploadedFile(null);
    setError(null);
    setKeyChange(0);
    setCapoPosition(0);
    setArpeggioRatio(0.5);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 via-purple-600 to-purple-800">
      <div className="container mx-auto px-4 py-8">
        {/* 헤더 */}
        <Header />

        {/* 에러 메시지 */}
        {error && (
          <ErrorMessage 
            message={error} 
            onClose={clearError}
          />
        )}

        {/* 메인 컨텐츠 */}
        <div className="mt-8 space-y-8">
          {/* 파일 업로드 섹션 */}
          {!analysisResult && (
            <div className="fade-in">
              <FileUpload 
                onFileUpload={handleFileUpload}
                isLoading={isLoading}
              />
            </div>
          )}

          {/* 로딩 상태 */}
          {isLoading && (
            <div className="flex justify-center">
              <LoadingSpinner />
            </div>
          )}

          {/* 분석 결과 */}
          {analysisResult && !isLoading && (
            <div className="space-y-8 fade-in">
              {/* 컨트롤 패널 */}
              <ControlPanel
                currentSettings={{
                  keyChange,
                  capoPosition,
                  arpeggioRatio
                }}
                analysisResult={analysisResult}
                onSettingsChange={handleSettingsChange}
                onClearResults={clearResults}
              />

              {/* 분석 정보 카드 */}
              <div className="bg-white rounded-xl shadow-lg p-6">
                <h3 className="text-lg font-semibold text-gray-800 mb-4">
                  🎵 분석 결과
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-600">파일명</div>
                    <div className="font-semibold">{analysisResult.filename}</div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-600">키</div>
                    <div className="font-semibold">{analysisResult.analysis.key}</div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-600">템포</div>
                    <div className="font-semibold">{Math.round(analysisResult.analysis.tempo)} BPM</div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-600">길이</div>
                    <div className="font-semibold">
                      {Math.floor(analysisResult.analysis.duration / 60)}:
                      {String(Math.floor(analysisResult.analysis.duration % 60)).padStart(2, '0')}
                    </div>
                  </div>
                </div>
              </div>

              {/* 코드 차트와 타브 */}
              <div className="grid lg:grid-cols-2 gap-8">
                {/* 코드 차트 */}
                <ChordChart 
                  chords={analysisResult.chords}
                  chordDiagrams={analysisResult.tab?.chord_diagrams}
                />

                {/* 타브 악보 */}
                <TabDisplay 
                  tabData={analysisResult.tab}
                  chords={analysisResult.chords}
                  analysisInfo={analysisResult.analysis}
                />
              </div>
            </div>
          )}
        </div>

        {/* 푸터 */}
        <footer className="mt-16 text-center text-white/70 text-sm">
          <div className="bg-black/10 rounded-lg p-4">
            <p>🎸 AI 기반 기타 타브악보 자동 생성기</p>
            <p className="mt-1">음악을 업로드하면 AI가 자동으로 기타 악보를 만들어드립니다</p>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default App;