import axios from 'axios';

// API 기본 설정
const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 5분 타임아웃 (음성 분석은 시간이 오래 걸릴 수 있음)
  headers: {
    'Content-Type': 'multipart/form-data',
  },
});

// 요청 인터셉터 - 로깅
api.interceptors.request.use(
  (config) => {
    console.log(`API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    console.error('API Request Error:', error);
    return Promise.reject(error);
  }
);

// 응답 인터셉터 - 에러 처리
api.interceptors.response.use(
  (response) => {
    console.log(`API Response: ${response.status} ${response.config.url}`);
    return response;
  },
  (error) => {
    console.error('API Response Error:', error);
    
    if (error.response) {
      // 서버에서 응답을 받았지만 에러 상태
      const { status, data } = error.response;
      let errorMessage = `서버 오류 (${status})`;
      
      if (data?.detail) {
        errorMessage = data.detail;
      } else if (data?.message) {
        errorMessage = data.message;
      }
      
      throw new Error(errorMessage);
    } else if (error.request) {
      // 요청을 보냈지만 응답을 받지 못함
      throw new Error('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.');
    } else {
      // 요청 설정 중 에러
      throw new Error('요청 처리 중 오류가 발생했습니다.');
    }
  }
);

/**
 * 오디오 파일을 분석하여 기타 타브 악보를 생성합니다.
 * @param {File} file - 분석할 오디오/비디오 파일
 * @param {Object} options - 분석 옵션
 * @param {number} options.keyChange - 키 변경 (반음 단위)
 * @param {number} options.capoPosition - 카포 위치
 * @param {number} options.arpeggioRatio - 아르페지오 비율 (0.0 ~ 1.0)
 * @returns {Promise<Object>} 분석 결과
 */
export const analyzeAudio = async (file, options = {}) => {
  const formData = new FormData();
  formData.append('file', file);
  
  // 옵션 파라미터 추가
  if (options.keyChange !== undefined) {
    formData.append('key_change', options.keyChange.toString());
  }
  if (options.capoPosition !== undefined) {
    formData.append('capo_position', options.capoPosition.toString());
  }
  if (options.arpeggioRatio !== undefined) {
    formData.append('arpeggio_ratio', options.arpeggioRatio.toString());
  }

  try {
    const response = await api.post('/analyze', formData);
    return response.data;
  } catch (error) {
    console.error('Audio analysis failed:', error);
    throw error;
  }
};

/**
 * 기존 코드를 이조합니다.
 * @param {Array} chords - 코드 배열
 * @param {number} semitones - 이조할 반음 수
 * @returns {Promise<Object>} 이조된 코드
 */
export const transposeChords = async (chords, semitones) => {
  try {
    const response = await api.post('/transpose', {
      chords,
      semitones
    }, {
      headers: {
        'Content-Type': 'application/json',
      },
    });
    return response.data;
  } catch (error) {
    console.error('Chord transposition failed:', error);
    throw error;
  }
};

/**
 * 기존 코드로부터 타브 악보만 재생성합니다.
 * @param {Array} chords - 코드 배열
 * @param {Object} options - 생성 옵션
 * @param {number} options.arpeggioRatio - 아르페지오 비율
 * @param {number} options.tempo - 템포
 * @param {string} options.timeSignature - 박자
 * @returns {Promise<Object>} 타브 데이터
 */
export const generateTab = async (chords, options = {}) => {
  try {
    const response = await api.post('/generate-tab', {
      chords,
      arpeggio_ratio: options.arpeggioRatio || 0.5,
      tempo: options.tempo || 120,
      time_signature: options.timeSignature || '4/4'
    }, {
      headers: {
        'Content-Type': 'application/json',
      },
    });
    return response.data;
  } catch (error) {
    console.error('Tab generation failed:', error);
    throw error;
  }
};

/**
 * 서버 상태를 확인합니다.
 * @returns {Promise<Object>} 서버 상태
 */
export const checkServerStatus = async () => {
  try {
    const response = await api.get('/');
    return response.data;
  } catch (error) {
    console.error('Server status check failed:', error);
    throw error;
  }
};

// 파일 크기 제한 체크
export const validateFile = (file) => {
  const maxSize = 100 * 1024 * 1024; // 100MB
  const allowedTypes = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/m4a',
    'video/mp4', 'video/avi', 'video/mov', 'video/quicktime'
  ];

  if (file.size > maxSize) {
    throw new Error('파일 크기는 100MB를 초과할 수 없습니다.');
  }

  if (!allowedTypes.includes(file.type) && !file.name.match(/\.(mp3|wav|m4a|mp4|avi|mov)$/i)) {
    throw new Error('지원하지 않는 파일 형식입니다. MP3, WAV, M4A, MP4, AVI, MOV 파일만 업로드 가능합니다.');
  }

  return true;
};