#!/usr/bin/env bash
# 탭 렌더 모드 관련 환경 변수를 현재 셸에서 unset.
# 사용: source backend/scripts/clear_tab_experiment_env.sh
# (반드시 source로 실행해야 부모 셸에 반영됩니다.)
unset TAB_RENDER_MODE TAB_ARRANGEMENT_MIN_RECALL
echo "[clear_tab_experiment_env] unset 완료"
