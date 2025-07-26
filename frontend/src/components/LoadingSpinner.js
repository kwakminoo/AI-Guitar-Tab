import React from 'react';
import { FaGuitar, FaMusic, FaRobot } from 'react-icons/fa';

const LoadingSpinner = () => {
  return (
    <div className="bg-white rounded-xl shadow-lg p-8 max-w-md mx-auto text-center">
      <div className="space-y-6">
        {/* 메인 로딩 애니메이션 */}
        <div className="relative">
          <div className="animate-spin rounded-full h-20 w-20 border-4 border-gray-200 border-t-primary-500 mx-auto"></div>
          <div className="absolute inset-0 flex items-center justify-center">
            <FaGuitar className="text-2xl text-primary-500 animate-pulse" />
          </div>
        </div>

        {/* 상태 텍스트 */}
        <div>
          <h3 className="text-xl font-semibold text-gray-800 mb-2">
            AI가 음악을 분석하고 있습니다
          </h3>
          <p className="text-gray-600">
            잠시만 기다려주세요<span className="loading-dots"></span>
          </p>
        </div>

        {/* 진행 단계 표시 */}
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-center space-x-3 text-blue-600">
            <FaMusic className="animate-pulse" />
            <span>오디오 신호 분석 중...</span>
          </div>
          
          <div className="flex items-center justify-center space-x-3 text-green-600">
            <FaRobot className="animate-bounce" />
            <span>AI 코드 인식 진행 중...</span>
          </div>
          
          <div className="flex items-center justify-center space-x-3 text-purple-600">
            <FaGuitar className="animate-pulse" />
            <span>기타 타브 악보 생성 중...</span>
          </div>
        </div>

        {/* 프로그레스 바 */}
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div className="bg-gradient-to-r from-primary-500 to-primary-600 h-2 rounded-full animate-pulse" style={{width: '60%'}}></div>
        </div>

        {/* 예상 시간 */}
        <div className="text-xs text-gray-500">
          <p>예상 소요 시간: 1-5분</p>
          <p className="mt-1">파일 크기와 복잡도에 따라 시간이 달라질 수 있습니다</p>
        </div>
      </div>
    </div>
  );
};

export default LoadingSpinner;