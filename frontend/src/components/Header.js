import React from 'react';
import { FaGuitar, FaMusic, FaRobot } from 'react-icons/fa';

const Header = () => {
  return (
    <header className="text-center text-white">
      <div className="flex justify-center items-center mb-4">
        <div className="bg-white/10 rounded-full p-4 mr-4">
          <FaGuitar className="text-4xl text-yellow-300" />
        </div>
        <div>
          <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-yellow-300 to-orange-300 bg-clip-text text-transparent">
            AI 기타 타브 생성기
          </h1>
          <div className="flex items-center justify-center mt-2 space-x-2 text-white/80">
            <FaRobot className="text-lg" />
            <span>AI 음성 분석</span>
            <span>•</span>
            <FaMusic className="text-lg" />
            <span>자동 코드 추출</span>
            <span>•</span>
            <FaGuitar className="text-lg" />
            <span>타브 악보 생성</span>
          </div>
        </div>
      </div>
      
      <p className="text-lg md:text-xl text-white/90 max-w-3xl mx-auto leading-relaxed">
        음악 파일을 업로드하면 <span className="font-semibold text-yellow-300">AI가 자동으로</span> 
        코드를 분석하고 <span className="font-semibold text-yellow-300">기타 타브 악보</span>를 생성해드립니다
      </p>
      
      <div className="mt-6 flex flex-wrap justify-center gap-4 text-sm text-white/70">
        <div className="bg-white/10 rounded-full px-4 py-2">
          🎵 MP3, WAV, MP4 지원
        </div>
        <div className="bg-white/10 rounded-full px-4 py-2">
          🎸 실시간 키 변환
        </div>
        <div className="bg-white/10 rounded-full px-4 py-2">
          🎼 아르페지오/스트로크 조절
        </div>
        <div className="bg-white/10 rounded-full px-4 py-2">
          📱 카포 위치 설정
        </div>
      </div>
    </header>
  );
};

export default Header;