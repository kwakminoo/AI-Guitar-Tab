/**
 * alphaTab @coderline/alphatab 1.x — 공식 문서·.d.ts 기준 모델·표기 참조.
 * (도형 SVG 에셋이 아니라 런타임 모델/프로퍼티 이름)
 */

export const ALPHATAB_SCORE_HIERARCHY: { ko: string; en: string }[] = [
  { ko: "악보 루트", en: "Score" },
  { ko: "마디 공통(박자·조표 등)", en: "MasterBar (score.masterBars)" },
  { ko: "트랙(악기/파트)", en: "Track" },
  { ko: "스태프(논리 오선)", en: "Staff" },
  { ko: "마디", en: "Bar" },
  { ko: "성부", en: "Voice" },
  { ko: "박(동시에 치는 음 묶음)", en: "Beat" },
  { ko: "음표 하나", en: "Note" },
];

export const ALPHATAB_NOTE_MODEL: { ko: string; api: string }[] = [
  { ko: "악센트/강약 계열", api: "accentuated (AccentuationType)" },
  { ko: "벤드 종류", api: "bendType (BendType)" },
  { ko: "벤드 스타일", api: "bendStyle (BendStyle)" },
  { ko: "벤드 이어짐 원점", api: "bendOrigin" },
  { ko: "벤드 포인트 목록", api: "bendPoints" },
  { ko: "해머온/풀오프 시작", api: "isHammerPullOrigin" },
  { ko: "해머온/풀오프 연결", api: "hammerPullOrigin / hammerPullDestination" },
  { ko: "하모닉 종류", api: "harmonicType (HarmonicType)" },
  { ko: "하모닉 피치 값", api: "harmonicValue" },
  { ko: "고스트 노트", api: "isGhost" },
  { ko: "렛 링", api: "isLetRing / letRingDestination" },
  { ko: "팜 뮤트", api: "isPalmMute / palmMuteDestination" },
  { ko: "데드 노트", api: "isDead" },
  { ko: "스타카토", api: "isStaccato" },
  { ko: "슬라이드 인", api: "slideInType (SlideInType)" },
  { ko: "슬라이드 아웃", api: "slideOutType (SlideOutType)" },
  { ko: "슬라이드 대상/출발", api: "slideTarget / slideOrigin" },
  { ko: "비브라토", api: "vibrato (VibratoType)" },
  { ko: "타이", api: "tieOrigin / tieDestination / isTieDestination" },
  { ko: "좌/우손 손가락", api: "leftHandFinger / rightHandFinger (Fingers)" },
  { ko: "트릴", api: "trillValue / trillSpeed (Duration)" },
  { ko: "다이나믹", api: "dynamics (DynamicValue)" },
  { ko: "오너먼트", api: "ornament (NoteOrnament)" },
  { ko: "이펙트 슬러", api: "effectSlurOrigin / effectSlurDestination" },
  { ko: "슬러(일반)", api: "slurOrigin / slurDestination / isSlurDestination" },
  { ko: "현·프렛(기타)", api: "string / fret" },
  { ko: "피아노 음", api: "octave / tone" },
  { ko: "타건", api: "percussionArticulation" },
];

export const ALPHATAB_BEAT_MODEL: { ko: string; api: string }[] = [
  { ko: "와미 바(트렘로 바)", api: "whammyBarType / whammyBarPoints / isContinuedWhammy" },
  { ko: "박 단위 비브라토", api: "vibrato (VibratoType)" },
  { ko: "코드", api: "chordId / chord" },
  { ko: "그레이스", api: "graceType / graceGroup / graceIndex" },
  { ko: "픽 스트로크", api: "pickStroke (PickStroke)" },
  { ko: "트레몰로 피킹", api: "tremoloPicking / isTremolo" },
  { ko: "크레셴도/디크레셴도", api: "crescendo (CrescendoType)" },
  { ko: "라스게아도", api: "hasRasgueado" },
  { ko: "슬랩/팝/탭", api: "slap / pop / tap" },
  { ko: "브러시", api: "brushType / brushDuration" },
  { ko: "튜플렛", api: "tupletNumerator / tupletDenominator / tupletGroup" },
  { ko: "페이드", api: "fade (FadeType)" },
  { ko: "가사", api: "lyrics" },
  { ko: "텍스트", api: "text" },
  { ko: "페르마타", api: "fermata" },
  { ko: "옥타브", api: "ottava (Ottavia)" },
  { ko: "오토메이션", api: "automations" },
];

export const ALPHATAB_PIPELINE: { ko: string; en: string }[] = [
  { ko: "악보 로드·임포트", en: "Importer → model.Score" },
  { ko: "화면 도형(글리프) 생성", en: "ScoreRenderer → 시각 트리" },
  { ko: "재생 MIDI", en: "MidiFileGenerator / Synth" },
];
