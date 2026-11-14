; Inno Setup script for Clipper
#define MyAppName "Clipper"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Pedro"
#define MyAppExeName "Clipper.exe"
#define MyCliExeName "clipper.exe"
#define MyAppMutex "ClipperSingletonMutex_C11F0E42"

[Setup]
AppId={{C11F0E42-9A17-4B3C-8D20-CLIPPER0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppMutex={#MyAppMutex}
AppSupportURL=https://github.com/lhymite36-bot/clipper
DefaultDirName={localappdata}\Programs\Clipper
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=Clipper-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=Clipper.exe,clipper.exe,clip.exe
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ClipperApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Clipper web UI"
Name: "{group}\Clipper (Terminal)"; Filename: "{app}\{#MyCliExeName}"; Comment: "Clipper command line"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Clipper"; Flags: nowait postinstall skipifsilent

[Code]
function KillImage(const Name: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('taskkill.exe', '/F /IM ' + Name, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  KillImage('Clipper.exe');
  KillImage('clipper.exe');
  KillImage('clip.exe');
  Sleep(400);
end;
