; 负责使用 Inno Setup 将已准备好的 EvidenceOps 源码与启动入口打包成 Windows 安装程序。
#define AppName "EvidenceOps"
#define AppVersion "0.1.0"
#define AppPublisher "EvidenceOps"
#define AppExeName "EvidenceOps启动.cmd"

[Setup]
AppId={{8F6B8D1A-1D1D-4FE3-8B2E-9BC0A4D3F091}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\EvidenceOps\app
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=EvidenceOps-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName={#AppName}

[Files]
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__\*;*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\alembic\*"; DestDir: "{app}\alembic"; Excludes: "__pycache__\*;*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\samples\*"; DestDir: "{app}\samples"; Flags: recursesubdirs ignoreversion
Source: "..\frontend\*"; DestDir: "{app}\frontend"; Excludes: "node_modules\*;.next\*;.env*;*.tsbuildinfo"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\start_installed.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\install_windows.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\alembic.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "EvidenceOps启动.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\EvidenceOps\data"
Name: "{localappdata}\EvidenceOps\logs"

[Icons]
Name: "{autodesktop}\EvidenceOps"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\EvidenceOps"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File `"{app}\scripts\install_windows.ps1`" -RepositoryDirectory `"{app}`" -DataDirectory `"{localappdata}\EvidenceOps\data`""; Flags: postinstall waituntilterminated; StatusMsg: "正在准备 Python、Node.js、网页和后端依赖..."

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not IsWin64 then
    Result := 'EvidenceOps 安装包需要 64 位 Windows。';
end;
