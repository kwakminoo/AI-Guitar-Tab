import React, { useState } from 'react';
import ReactSlider from 'react-slider';
import { FaArrowUp, FaArrowDown, FaGuitar, FaRedo, FaDownload, FaCog } from 'react-icons/fa';

const ControlPanel = ({ currentSettings, analysisResult, onSettingsChange, onClearResults }) => {
  const [keyChange, setKeyChange] = useState(currentSettings.keyChange);
  const [capoPosition, setCapoPosition] = useState(currentSettings.capoPosition);
  const [arpeggioRatio, setArpeggioRatio] = useState(currentSettings.arpeggioRatio);
  const [isExpanded, setIsExpanded] = useState(false);

  const handleApplySettings = () => {
    onSettingsChange({
      keyChange,
      capoPosition,
      arpeggioRatio
    });
  };

  const getKeyChangeText = (semitones) => {
    if (semitones === 0) return '원곡';
    const direction = semitones > 0 ? '+' : '';
    return `${direction}${semitones} 반음`;
  };

  const getRatioText = (ratio) => {
    if (ratio <= 0.2) return '거의 스트로크';
    if (ratio <= 0.4) return '스트로크 위주';
    if (ratio <= 0.6) return '균형';
    if (ratio <= 0.8) return '아르페지오 위주';
    return '거의 아르페지오';
  };

  return (
    <div className="bg-white rounded-xl shadow-lg overflow-hidden">
      {/* 헤더 */}
      <div className="bg-gradient-to-r from-primary-500 to-primary-600 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <FaCog className="text-white text-xl" />
            <h3 className="text-xl font-semibold text-white">설정 및 조절</h3>
          </div>
          
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="bg-white/20 hover:bg-white/30 text-white px-3 py-1 rounded-lg text-sm transition-colors"
            >
              {isExpanded ? '접기' : '펼치기'}
            </button>
            
            <button
              onClick={onClearResults}
              className="bg-white/20 hover:bg-white/30 text-white px-3 py-1 rounded-lg text-sm transition-colors flex items-center space-x-1"
            >
              <FaRedo className="text-xs" />
              <span>새 파일</span>
            </button>
          </div>
        </div>
      </div>

      {/* 컨텐츠 */}
      <div className={`p-6 transition-all duration-300 ${isExpanded ? 'block' : 'hidden'}`}>
        <div className="grid md:grid-cols-3 gap-6">
          {/* 키 변경 */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-gray-700">
              🎵 키 변경 (반음 단위)
            </label>
            <div className="space-y-2">
              <ReactSlider
                value={keyChange}
                onChange={setKeyChange}
                min={-12}
                max={12}
                step={1}
                className="h-6 bg-gray-200 rounded-lg"
                thumbClassName="h-6 w-6 bg-primary-500 rounded-full cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary-300"
                trackClassName="bg-primary-200 rounded-lg"
              />
              <div className="flex justify-between text-xs text-gray-500">
                <span>-12</span>
                <span className="font-semibold text-primary-600">
                  {getKeyChangeText(keyChange)}
                </span>
                <span>+12</span>
              </div>
            </div>
          </div>

          {/* 카포 위치 */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-gray-700">
              🎸 카포 위치 (프렛)
            </label>
            <div className="space-y-2">
              <ReactSlider
                value={capoPosition}
                onChange={setCapoPosition}
                min={0}
                max={12}
                step={1}
                className="h-6 bg-gray-200 rounded-lg"
                thumbClassName="h-6 w-6 bg-guitar-500 rounded-full cursor-pointer focus:outline-none focus:ring-2 focus:ring-guitar-300"
                trackClassName="bg-guitar-200 rounded-lg"
              />
              <div className="flex justify-between text-xs text-gray-500">
                <span>0</span>
                <span className="font-semibold text-guitar-600">
                  {capoPosition === 0 ? '카포 없음' : `${capoPosition}프렛`}
                </span>
                <span>12</span>
              </div>
            </div>
          </div>

          {/* 아르페지오 비율 */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-gray-700">
              🎼 연주 스타일
            </label>
            <div className="space-y-2">
              <ReactSlider
                value={arpeggioRatio}
                onChange={setArpeggioRatio}
                min={0}
                max={1}
                step={0.1}
                className="h-6 bg-gray-200 rounded-lg"
                thumbClassName="h-6 w-6 bg-purple-500 rounded-full cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-300"
                trackClassName="bg-purple-200 rounded-lg"
              />
              <div className="flex justify-between text-xs text-gray-500">
                <span>스트로크</span>
                <span className="font-semibold text-purple-600">
                  {getRatioText(arpeggioRatio)}
                </span>
                <span>아르페지오</span>
              </div>
            </div>
          </div>
        </div>

        {/* 적용 버튼 */}
        <div className="mt-6 flex justify-center">
          <button
            onClick={handleApplySettings}
            className="bg-primary-500 hover:bg-primary-600 text-white px-8 py-3 rounded-lg font-semibold transition-colors flex items-center space-x-2"
          >
            <FaGuitar />
            <span>설정 적용하여 재생성</span>
          </button>
        </div>
      </div>

      {/* 간단한 요약 (접혔을 때) */}
      {!isExpanded && (
        <div className="p-4 bg-gray-50 text-sm text-gray-600">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <span>키: {getKeyChangeText(keyChange)}</span>
              <span>카포: {capoPosition === 0 ? '없음' : `${capoPosition}프렛`}</span>
              <span>스타일: {getRatioText(arpeggioRatio)}</span>
            </div>
            <span className="text-xs text-gray-400">설정을 변경하려면 펼치기를 클릭하세요</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default ControlPanel;