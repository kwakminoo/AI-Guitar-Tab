---
name: review-comment-classifier
description: >-
  Classifies a single code-review comment as Critical, Major, Minor, or Invalid
  using severity definitions below. Use when the user pastes a reviewer comment,
  asks whether to accept a review note, triages PR feedback, or says 리뷰
  코멘트 분류/검증/타당성.
---

# 코드 리뷰 코멘트 분류(검증)

사용자가 **리뷰어 코멘트**(및 가능하면 관련 **코드/디프 맥락**)를 주면, 아래 네 가지 중 **정확히 하나**로 분류한다.

## 분류 정의

| 등급 | 조건 |
|------|------|
| **Critical** | 리뷰가 타당하고, **즉시 수정하지 않으면** 장애·보안 취약·데이터 손실 등 **심각한 사고**로 이어질 수 있음. |
| **Major** | 리뷰가 타당하고, **기능 오류** 또는 **유지보수성·확장성**을 크게 해칠 수 있는 중요 수정. |
| **Minor** | 리뷰가 타당하지만 **권장 수준**(가독성, 네이밍, 컨벤션, 소규모 리팩터 등). 당장 머지를 막을 정도는 아님. |
| **Invalid** | 리뷰가 **부정확·과도·맥락 오해**이며, **현재 코드/요구사항 기준**으로는 수정이 불필요하거나 대안이 이미 충족됨. |

## 수행 절차

1. 코멘트가 지적하는 **파일/라인/동작**을 식별한다. 코드가 주어지지 않았으면 **가정을 명시**하거나, 필요한 최소 맥락을 한 줄로 요청한다.
2. 지적이 **사실에 부합하는지** 판단한다(과장, 일반론, 다른 스택 관습 강요 등은 Invalid 후보).
3. 위 표에 맞춰 **한 등급만** 선택한다. 애매하면 **더 높은 등급**을 택하되, 근거에 “불확실성”을 한 문장으로 적는다.

## 출력 형식(고정)

아래 순서로 **한국어**로 답한다.

```markdown
## 분류: Critical | Major | Minor | Invalid

## 한 줄 요약
(코멘트의 핵심 주장을 한 문장으로)

## 판단 근거
- (불릿 2~4개: 코드/요구사항과의 관계)

## 권장 조치
- Critical/Major/Minor: 무엇을 어떻게 바꿀지 1~3문장
- Invalid: 왜 반박 가능한지 1~3문장(필요 시 리뷰어에게 보낼 답변 초안 1문단)

## 추가로 필요한 맥락(있다면)
- (없으면 "없음")
```

## 예시(간단)

- “여기서 SQL 문자열 연결하면 인젝션입니다” + 실제로 외부 입력이 raw SQL에 들어감 → **Critical**
- “이 캐시 키가 사용자별로 구분되지 않습니다” + 다중 테넌트 → **Major**
- “변수명 `data`보다 `audioBuffer`가 낫습니다” → **Minor**
- “반드시 싱글톤이어야 합니다”인데 요청은 stateless 워커 → **Invalid** (근거 명시)
