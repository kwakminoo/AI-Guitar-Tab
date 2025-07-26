import React, { useState } from 'react';
import { FaGuitar, FaPlay, FaPause, FaExpand } from 'react-icons/fa';

const ChordChart = ({ chords, chordDiagrams }) => {
  const [selectedChord, setSelectedChord] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const getDifficultyColor = (difficulty) => {
    switch (difficulty) {
      case 1: return 'text-green-500';
      case 2: return 'text-yellow-500';
      case 3: return 'text-orange-500';
      case 4: return 'text-red-500';
      case 5: return 'text-purple-500';
      default: return 'text-gray-500';
    }
  };

  const getDifficultyText = (difficulty) => {
    switch (difficulty) {
      case 1: return '초급';
      case 2: return '초-중급';
      case 3: return '중급';
      case 4: return '중-고급';
      case 5: return '고급';
      default: return '알 수 없음';
    }
  };

  const renderChordDiagram = (chordName, diagram) => {
    if (!diagram || !diagram.positions) return null;

    return (
      <div className="bg-gray-50 rounded-lg p-4">
        <div className="text-center mb-3">
          <h4 className="font-bold text-lg text-gray-800">{chordName}</h4>
          <div className={`text-xs ${getDifficultyColor(diagram.difficulty)}`}>
            {getDifficultyText(diagram.difficulty)}
          </div>
        </div>
        
        {/* 기타 프렛보드 */}
        <div className="relative">
          {/* 프렛 */}
          <div className="grid grid-rows-4 gap-1 mb-2">
            {[1, 2, 3, 4].map(fret => (
              <div key={fret} className="h-1 bg-gray-300 rounded"></div>
            ))}
          </div>
          
          {/* 줄과 포지션 */}
          <div className="absolute top-0 left-0 right-0 bottom-0">
            <div className="grid grid-cols-6 h-full">
              {diagram.positions.map((position, stringIndex) => (
                <div key={stringIndex} className="relative flex flex-col justify-between border-r border-gray-300 last:border-r-0">
                  {/* 줄 */}
                  <div className="absolute top-0 bottom-0 left-1/2 w-0.5 bg-gray-400 transform -translate-x-1/2"></div>
                  
                  {/* 포지션 마커 */}
                  {position !== null && position > 0 && (
                    <div 
                      className="absolute w-4 h-4 bg-blue-500 rounded-full border-2 border-white left-1/2 transform -translate-x-1/2"
                      style={{ 
                        top: `${(position - 1) * 25}%`,
                        marginTop: '-8px'
                      }}
                    >
                      <span className="absolute inset-0 flex items-center justify-center text-xs text-white font-bold">
                        {diagram.fingers && diagram.fingers[stringIndex] ? diagram.fingers[stringIndex] : ''}
                      </span>
                    </div>
                  )}
                  
                  {/* 오픈 스트링 */}
                  {position === 0 && (
                    <div className="absolute -top-3 left-1/2 transform -translate-x-1/2 w-3 h-3 border-2 border-green-500 rounded-full bg-white"></div>
                  )}
                  
                  {/* 뮤트된 스트링 */}
                  {position === null && (
                    <div className="absolute -top-3 left-1/2 transform -translate-x-1/2 text-red-500 font-bold text-sm">×</div>
                  )}
                </div>
              ))}
            </div>
          </div>
          
          {/* 스트링 라벨 */}
          <div className="grid grid-cols-6 text-xs text-gray-500 mt-2 text-center">
            {['E', 'A', 'D', 'G', 'B', 'E'].map((note, index) => (
              <div key={index}>{note}</div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-white rounded-xl shadow-lg overflow-hidden">
      {/* 헤더 */}
      <div className="bg-gradient-to-r from-guitar-500 to-guitar-600 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <FaGuitar className="text-white text-xl" />
            <h3 className="text-xl font-semibold text-white">코드 진행</h3>
          </div>
          <div className="text-white/80 text-sm">
            총 {chords?.length || 0}개 코드
          </div>
        </div>
      </div>

      <div className="p-6">
        {/* 코드 타임라인 */}
        <div className="mb-6">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">⏱️ 코드 타임라인</h4>
          <div className="max-h-40 overflow-y-auto border rounded-lg">
            {chords && chords.length > 0 ? (
              <div className="space-y-1 p-2">
                {chords.map((chord, index) => (
                  <div 
                    key={index}
                    className={`flex items-center justify-between p-2 rounded cursor-pointer transition-colors
                      ${selectedChord === chord.chord ? 'bg-guitar-100 border border-guitar-300' : 'hover:bg-gray-50'}
                    `}
                    onClick={() => setSelectedChord(chord.chord)}
                  >
                    <div className="flex items-center space-x-3">
                      <span className="font-mono text-sm bg-gray-100 px-2 py-1 rounded">
                        {formatTime(chord.start_time)}
                      </span>
                      <span className="font-semibold text-lg text-guitar-700">
                        {chord.chord}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500">
                      {chord.duration?.toFixed(1)}초
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center text-gray-500">
                코드 정보가 없습니다
              </div>
            )}
          </div>
        </div>

        {/* 선택된 코드 다이어그램 */}
        {selectedChord && chordDiagrams && chordDiagrams[selectedChord] && (
          <div className="mb-6">
            <h4 className="text-sm font-semibold text-gray-700 mb-3">🎸 선택된 코드</h4>
            {renderChordDiagram(selectedChord, chordDiagrams[selectedChord])}
          </div>
        )}

        {/* 모든 코드 다이어그램 그리드 */}
        {chordDiagrams && Object.keys(chordDiagrams).length > 0 && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-3">🎼 사용된 모든 코드</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 max-h-96 overflow-y-auto">
              {Object.entries(chordDiagrams).map(([chordName, diagram]) => (
                <div 
                  key={chordName}
                  className={`cursor-pointer transition-all duration-200 hover:scale-105
                    ${selectedChord === chordName ? 'ring-2 ring-guitar-400 rounded-lg' : ''}
                  `}
                  onClick={() => setSelectedChord(chordName)}
                >
                  {renderChordDiagram(chordName, diagram)}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 코드가 없을 때 */}
        {(!chords || chords.length === 0) && (!chordDiagrams || Object.keys(chordDiagrams).length === 0) && (
          <div className="text-center py-12">
            <FaGuitar className="text-6xl text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-600 mb-2">
              코드 정보가 없습니다
            </h3>
            <p className="text-gray-500">
              음악 파일을 분석하면 코드 정보가 여기에 표시됩니다
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChordChart;