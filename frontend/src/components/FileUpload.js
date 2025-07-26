import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { FaCloudUploadAlt, FaMusic, FaVideo, FaFileAudio } from 'react-icons/fa';
import { validateFile } from '../services/api';

const FileUpload = ({ onFileUpload, isLoading }) => {
  const [dragActive, setDragActive] = useState(false);

  const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
    setDragActive(false);
    
    if (rejectedFiles.length > 0) {
      const rejection = rejectedFiles[0];
      let errorMessage = '파일 업로드 실패';
      
      if (rejection.errors) {
        const error = rejection.errors[0];
        if (error.code === 'file-too-large') {
          errorMessage = '파일 크기가 너무 큽니다. 100MB 이하의 파일을 선택해주세요.';
        } else if (error.code === 'file-invalid-type') {
          errorMessage = '지원하지 않는 파일 형식입니다.';
        }
      }
      
      alert(errorMessage);
      return;
    }

    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0];
      
      try {
        validateFile(file);
        onFileUpload(file);
      } catch (error) {
        alert(error.message);
      }
    }
  }, [onFileUpload]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDragEnter: () => setDragActive(true),
    onDragLeave: () => setDragActive(false),
    accept: {
      'audio/*': ['.mp3', '.wav', '.m4a'],
      'video/*': ['.mp4', '.avi', '.mov']
    },
    maxSize: 100 * 1024 * 1024, // 100MB
    multiple: false,
    disabled: isLoading
  });

  const getFileIcon = () => {
    if (isDragActive || dragActive) {
      return <FaCloudUploadAlt className="text-6xl text-primary-500 animate-bounce" />;
    }
    return <FaMusic className="text-6xl text-gray-400" />;
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div
        {...getRootProps()}
        className={`
          dropzone relative border-3 border-dashed rounded-2xl p-12 text-center cursor-pointer
          transition-all duration-300 bg-white shadow-lg hover:shadow-xl
          ${isDragActive || dragActive ? 'border-primary-500 bg-primary-50 active' : 'border-gray-300 hover:border-gray-400'}
          ${isLoading ? 'pointer-events-none opacity-60' : ''}
        `}
      >
        <input {...getInputProps()} />
        
        <div className="space-y-6">
          {/* 아이콘 */}
          <div className="flex justify-center">
            {getFileIcon()}
          </div>

          {/* 메인 텍스트 */}
          <div>
            <h3 className="text-2xl font-semibold text-gray-800 mb-2">
              {isDragActive ? '파일을 여기에 놓아주세요' : '음악 파일을 업로드하세요'}
            </h3>
            <p className="text-gray-600">
              {isDragActive 
                ? '파일을 드롭하면 분석이 시작됩니다' 
                : '클릭하거나 드래그 앤 드롭으로 파일을 업로드할 수 있습니다'
              }
            </p>
          </div>

          {/* 지원 파일 형식 */}
          <div className="flex flex-wrap justify-center gap-4 text-sm">
            <div className="flex items-center space-x-2 bg-gray-100 rounded-full px-4 py-2">
              <FaFileAudio className="text-blue-500" />
              <span>MP3, WAV, M4A</span>
            </div>
            <div className="flex items-center space-x-2 bg-gray-100 rounded-full px-4 py-2">
              <FaVideo className="text-red-500" />
              <span>MP4, AVI, MOV</span>
            </div>
          </div>

          {/* 제한 사항 */}
          <div className="text-xs text-gray-500 space-y-1">
            <p>• 최대 파일 크기: 100MB</p>
            <p>• 분석 시간: 파일 크기에 따라 1-5분 소요</p>
            <p>• 고품질 음원일수록 더 정확한 결과를 얻을 수 있습니다</p>
          </div>

          {/* 로딩 상태 */}
          {isLoading && (
            <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-2xl">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500 mx-auto"></div>
                <p className="mt-4 text-gray-600 font-medium">
                  파일 업로드 중<span className="loading-dots"></span>
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 도움말 */}
      <div className="mt-6 bg-white/10 rounded-lg p-4 text-white/80 text-sm">
        <h4 className="font-semibold mb-2">💡 더 좋은 결과를 위한 팁:</h4>
        <ul className="space-y-1 list-disc list-inside">
          <li>보컬과 기타가 명확하게 들리는 곡을 선택하세요</li>
          <li>너무 복잡하지 않은 편곡의 곡이 더 정확합니다</li>
          <li>인트로나 간주보다는 메인 멜로디 부분이 포함된 곡을 추천합니다</li>
          <li>음질이 좋을수록 더 정확한 코드 분석이 가능합니다</li>
        </ul>
      </div>
    </div>
  );
};

export default FileUpload;