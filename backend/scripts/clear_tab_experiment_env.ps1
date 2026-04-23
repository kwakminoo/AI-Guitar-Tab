# 탭 렌더 모드 관련 환경 변수를 현재 PowerShell 세션에서 제거합니다.
# 사용: repo 루트에서  .\backend\scripts\clear_tab_experiment_env.ps1
# 또는:  . .\backend\scripts\clear_tab_experiment_env.ps1  (동일)
$names = @(
    "TAB_RENDER_MODE",
    "TAB_ARRANGEMENT_MIN_RECALL"
)
foreach ($name in $names) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
Write-Host "[clear_tab_experiment_env] 제거됨: $($names -join ', ')" -ForegroundColor Green
