/**
 * 테스트 악보 탭(ScoreViewer)에서 불러오는 AlphaTex 소스.
 * 다른 악보로 바꿀 때는 아래 상수만 수정하면 API·폴백 URL·UI 안내가 함께 바뀝니다.
 * public 폴백 파일은 `TEST_SCORE_PUBLIC_FILE` 이름으로 `frontend/public/test-scores/`에 두세요.
 */
export const TEST_SCORE_DISPLAY_TITLE = "good-night-good-dream";

/** src 기준: frontend/src/ 아래 상대 경로 조각 */
export const TEST_SCORE_REL_SEGMENTS = ["test-scores", "너드커넥션-좋은 밤 좋은 꿈", "good-night-good-dream.atex"] as const;

/** 브라우저가 직접 요청하는 폴백: frontend/public/test-scores/<이름> */
export const TEST_SCORE_PUBLIC_FILE = "good-night-good-dream.atex";

export const TEST_SCORE_API_PATH = "/api/test-score/current" as const;

export const TEST_SCORE_PUBLIC_FALLBACK_URL = `/test-scores/${TEST_SCORE_PUBLIC_FILE}`;

/** UI·오류 메시지용: src/test-scores/... 전체 경로 문자열 */
export const TEST_SCORE_REL_PATH = TEST_SCORE_REL_SEGMENTS.join("/");
