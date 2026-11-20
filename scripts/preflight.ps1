# OneFeed 提测门禁：一条命令跑完前后端所有检查，任何一步红就停。
#
#   pwsh scripts/preflight.ps1            # 全量（测试 + UI 门禁 + 构建）
#   pwsh scripts/preflight.ps1 -SkipBuild # 只跑测试与门禁
#
# 为什么要有这个文件：tests/test_api.py 因为 feed 改成平台交错而断言过期，
# 但没人跑全量，一直显示「通过」。分散在几个命令里的门禁等于没有门禁。
#
# 网络：pytest 走 uv 的 --with 临时环境。代理没开时联网拉包会失败，
# 而 uv 缓存里通常已经有了 —— 先探一次离线，探不到再联网（那时需要代理）。

param(
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($name, $block) {
  Write-Host ""
  Write-Host "==> $name" -ForegroundColor Cyan
  $started = Get-Date
  & $block
  if ($LASTEXITCODE -ne 0) {
    throw "$name 失败（退出码 $LASTEXITCODE）"
  }
  $ms = [int]((Get-Date) - $started).TotalMilliseconds
  Write-Host "    ok ($ms ms)" -ForegroundColor Green
}

# 缓存里有 pytest 就走离线，省得每次都被代理卡 15 秒
uv run --offline --with pytest python -c "import pytest" 2>$null | Out-Null
$offline = $LASTEXITCODE -eq 0
if (-not $offline) {
  Write-Host "uv 缓存里没有 pytest，联网拉一次（需要代理）" -ForegroundColor Yellow
}
$uvArgs = if ($offline) { @("--offline", "--with", "pytest") } else { @("--with", "pytest") }

Step "pytest（单元与接口）" {
  uv run @uvArgs python -m pytest tests -q
}

Step "run_all（端到端回放，离线）" {
  uv run @uvArgs python tests/run_all.py --offline
}

Step "check-ui（字号/圆角/动效门禁）" {
  node web/scripts/check-ui.mjs
}

if (-not $SkipBuild) {
  Step "build（tsc + vite）" {
    Push-Location web
    try {
      npm run build
    } finally {
      Pop-Location
    }
  }
}

Write-Host ""
Write-Host "全部通过。" -ForegroundColor Green
