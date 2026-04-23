# 렌더 모드를 arrangement로 고정하고 품질 게이트 기준을 설정합니다.
# 끄려면: .\backend\scripts\clear_tab_experiment_env.ps1
$env:TAB_RENDER_MODE = "arrangement"
$env:TAB_ARRANGEMENT_MIN_RECALL = "0.80"
Write-Host "[tab_experiment_env_all_on] arrangement env 적용됨(TAB_RENDER_MODE, TAB_ARRANGEMENT_MIN_RECALL)." -ForegroundColor Cyan
