# 负责启动并监督本机前后端服务，统一数据目录，退出时清理本次创建的进程。
param([int]$ApiPort=8014,[int]$WebPort=3013,[string]$DataDirectory="")
$ErrorActionPreference="Stop"
$project_directory=Split-Path -Parent $PSScriptRoot
$python_path=Join-Path $project_directory ".venv/Scripts/python.exe"
$frontend_directory=Join-Path $project_directory "frontend"
$next_path=Join-Path $frontend_directory "node_modules/next/dist/bin/next"
if($PSVersionTable.PSVersion.Major-lt7){throw "请使用 PowerShell 7：pwsh -File scripts/start_installed.ps1"} # ArgumentList 正确处理带空格的路径。
if($ApiPort-lt1-or$ApiPort-gt65535-or$WebPort-lt1-or$WebPort-gt65535-or$ApiPort-eq$WebPort){throw "请指定两个不同的有效端口"}
if(!(Test-Path -LiteralPath $python_path)-or!(Test-Path -LiteralPath $next_path)-or!(Test-Path -LiteralPath (Join-Path $frontend_directory ".next/BUILD_ID"))){throw "依赖或前端构建未准备好，请先按 CUSTOMER_INSTALLATION.md 完成安装"}
$node_path=(Get-Command node -ErrorAction Stop).Source
if(!$DataDirectory){$DataDirectory=Join-Path $env:LOCALAPPDATA "EvidenceOps"}
$DataDirectory=[System.IO.Path]::GetFullPath($DataDirectory)
$children=[System.Collections.Generic.List[System.Diagnostics.Process]]::new()
function Start-ServiceProcess($executable,$directory,$arguments){
	$information=[System.Diagnostics.ProcessStartInfo]::new()
	$information.FileName=$executable;$information.WorkingDirectory=$directory
	$information.UseShellExecute=$false;$information.CreateNoWindow=$true
	$information.Environment["PYTHONPATH"]=Join-Path $project_directory "src"
	$information.Environment["EVIDENCEOPS_DATA_DIR"]=$DataDirectory
	$information.Environment["EVIDENCEOPS_API_URL"]="http://127.0.0.1:$ApiPort"
	foreach($argument in $arguments){$information.ArgumentList.Add([string]$argument)}
	$process=[System.Diagnostics.Process]::Start($information);$children.Add($process)
}
try{
	Start-ServiceProcess $python_path $project_directory @("-m","uvicorn","evidenceops.api.installed_app:app","--app-dir","src","--host","127.0.0.1","--port",$ApiPort)
	Start-ServiceProcess $node_path $frontend_directory @($next_path,"start","--hostname","127.0.0.1","--port",$WebPort)
	Write-Host "EvidenceOps 地址：http://127.0.0.1:$WebPort；按 Ctrl+C 停止。"
	while($true){foreach($process in $children){if($process.HasExited){throw "服务退出，请检查端口、目录权限与启动输出"}};Start-Sleep -Milliseconds 250}
}finally{
	foreach($process in $children){if(!$process.HasExited){$process.Kill($true);$process.WaitForExit()};$process.Dispose()}
} # 仅清理当前脚本启动的进程，不操作其他实例。
