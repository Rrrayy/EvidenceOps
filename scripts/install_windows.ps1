# 负责在 Windows 客户机准备 EvidenceOps 运行环境并创建启动快捷方式。
param(
	[string]$RepositoryDirectory=(Split-Path -Parent $PSScriptRoot),
	[string]$DataDirectory=(Join-Path $env:LOCALAPPDATA "EvidenceOps"),
	[switch]$SkipDependencyInstall
)

$ErrorActionPreference="Stop"
$RepositoryDirectory=[System.IO.Path]::GetFullPath($RepositoryDirectory)
$DataDirectory=[System.IO.Path]::GetFullPath($DataDirectory)

function Find-CommandPath($name){
	$command=Get-Command $name -ErrorAction SilentlyContinue
	if($command){return $command.Source}
	return $null
}

function Install-WingetPackage($id){
	if(!(Find-CommandPath "winget")){throw "未找到 winget。请安装 App Installer，或手动安装 $id。"}
	Write-Host "正在检查 $id ..."
	& winget install --id $id --source winget --accept-source-agreements --accept-package-agreements --silent
	if($LASTEXITCODE-ne0){throw "安装 $id 失败，退出码：$LASTEXITCODE"}
	$machine_path=[Environment]::GetEnvironmentVariable("Path","Machine")
	$user_path=[Environment]::GetEnvironmentVariable("Path","User")
	$env:Path="$machine_path;$user_path"
}

if(!(Test-Path (Join-Path $RepositoryDirectory "requirements.txt"))){throw "未找到项目根目录：$RepositoryDirectory"}
if(!$SkipDependencyInstall){
	if(!(Find-CommandPath "python")){Install-WingetPackage "Python.Python.3.14"}
	if(!(Find-CommandPath "node")){Install-WingetPackage "OpenJS.NodeJS.LTS"}
	if(!(Find-CommandPath "pwsh")){Install-WingetPackage "Microsoft.PowerShell"}
}

$python=Find-CommandPath "python"
$node=Find-CommandPath "node"
$npm=Find-CommandPath "npm.cmd"
$pwsh=Find-CommandPath "pwsh"
if(!$python-or!$node-or!$npm-or!$pwsh){throw "运行时未准备完整。需要 Python、Node.js、npm.cmd 和 PowerShell 7，请重新打开终端后重试。"}

$venv_python=Join-Path $RepositoryDirectory ".venv/Scripts/python.exe"
if(!(Test-Path $venv_python)){
	Write-Host "正在创建 Python 虚拟环境..."
	& $python -m venv (Join-Path $RepositoryDirectory ".venv")
	if($LASTEXITCODE-ne0){throw "创建 Python 虚拟环境失败"}
}
Write-Host "正在安装后端依赖..."
& $venv_python -m pip install -r (Join-Path $RepositoryDirectory "requirements.txt")
if($LASTEXITCODE-ne0){throw "后端依赖安装失败"}

$frontend=Join-Path $RepositoryDirectory "frontend"
Write-Host "正在安装并构建网页..."
Push-Location $frontend
try{
	& $npm ci
	if($LASTEXITCODE-ne0){throw "网页依赖安装失败"}
	& $npm run build
	if($LASTEXITCODE-ne0){throw "网页构建失败"}
}finally{Pop-Location}

New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$shortcut_directory=Join-Path $env:USERPROFILE "Desktop"
New-Item -ItemType Directory -Force -Path $shortcut_directory | Out-Null
$shortcut_path=Join-Path $shortcut_directory "EvidenceOps.lnk"
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut($shortcut_path)
$shortcut.TargetPath=$pwsh
$shortcut.Arguments="-NoProfile -File `"$(Join-Path $RepositoryDirectory 'scripts/start_installed.ps1')`" -DataDirectory `"$DataDirectory`""
$shortcut.WorkingDirectory=$RepositoryDirectory
$shortcut.Description="启动 EvidenceOps 网页控制台"
$shortcut.Save()
Write-Host "安装准备完成。桌面快捷方式：$shortcut_path"
Write-Host "首次启动：双击桌面 EvidenceOps，或执行 pwsh -File scripts/start_installed.ps1"
