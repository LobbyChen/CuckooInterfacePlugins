#Requires -Version 7.0
<#
.SYNOPSIS
    构建 CuckooIslandBase：编译 ClassIsland 桥接插件 → 同步产物 → 打包插件 zip。

.EXAMPLE
    ./build.ps1
    ./build.ps1 -ClassIslandDir "D:\Apps\ClassIsland"
#>
[CmdletBinding()]
param(
    [string]$ClassIslandDir = $env:CI_DIR,
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$pluginDir = $PSScriptRoot
$bridgeSrc = Join-Path $pluginDir "src"
$bridgeOut = Join-Path $pluginDir "island-bridge"
$distDir = Join-Path $pluginDir "dist"

function Find-CoreDir {
    param([string]$Dir)
    if (-not $Dir -or -not (Test-Path $Dir)) { return "" }
    if (Test-Path (Join-Path $Dir "ClassIsland.Core.dll")) { return $Dir }

    # 安装根目录：Core 在 app-x.y.z 子目录里
    $app = Get-ChildItem $Dir -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($app -and (Test-Path (Join-Path $app.FullName "ClassIsland.Core.dll"))) {
        return $app.FullName
    }
    return ""
}

function Resolve-ClassIslandDir {
    param([string]$Hint)

    $resolved = Find-CoreDir $Hint
    if ($resolved) { return $resolved }

    $registry = "HKCU:\Software\Classes\classisland\shell\open\command"
    if (Test-Path $registry) {
        $command = (Get-ItemProperty $registry).'(default)'
        if ($command) {
            $exe = $command.Trim()
            if ($exe.StartsWith('"')) { $exe = $exe.Substring(1, $exe.IndexOf('"', 1) - 1) }
            else { $exe = ($exe -split ' ')[0] }
            $resolved = Find-CoreDir (Split-Path -Parent $exe)
            if ($resolved) { return $resolved }
        }
    }

    return ""
}

$ciDir = Resolve-ClassIslandDir -Hint $ClassIslandDir
if (-not $ciDir) {
    Write-Warning "未找到 ClassIsland（缺少 ClassIsland.Core.dll）。"
    Write-Warning "请用 -ClassIslandDir 指定包含 ClassIsland.Core.dll 的目录，或设置环境变量 CI_DIR。"
    Write-Warning "将跳过 C# 构建，直接使用 island-bridge 下的现有 DLL 打包。"
} else {
    Write-Host "ClassIsland: $ciDir"
    dotnet build (Join-Path $bridgeSrc "CuckooIslandBridge.csproj") `
        -c $Configuration `
        -p:ClassIslandDir=$ciDir `
        --nologo
    if ($LASTEXITCODE -ne 0) { throw "构建 CuckooIslandBridge 失败" }

    New-Item -ItemType Directory -Force -Path $bridgeOut | Out-Null
    Copy-Item (Join-Path $bridgeSrc "bin\$Configuration\CuckooIslandBridge.dll") $bridgeOut -Force
    Copy-Item (Join-Path $bridgeSrc "manifest.yml") $bridgeOut -Force
    Write-Host "已同步桥接插件到 $bridgeOut"
}

$meta = Get-Content (Join-Path $pluginDir "META-INF.json") -Raw -Encoding utf8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
$zipPath = Join-Path $distDir ("CuckooIslandBase-{0}.zip" -f $meta.version)
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

# 只挑发布需要的文件，避免把 __pycache__ / runtime-state.json / 源码打进包里
$stage = Join-Path $distDir ".stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
foreach ($name in @("META-INF.json", "main.py", "config.html", "README.md")) {
    $source = Join-Path $pluginDir $name
    if (-not (Test-Path $source)) { throw "缺少插件文件：$name" }
    Copy-Item $source $stage -Force
}
Copy-Item $bridgeOut (Join-Path $stage "island-bridge") -Recurse -Force

# 注意：压缩包根目录必须直接是 META-INF.json / main.py，不能再套一层文件夹
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
Write-Host "已生成 $zipPath"
Write-Host "安装：把 zip 放进 CuckooInterface 的 user/Base/ 后重启。"
