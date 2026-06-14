; Inno Setup script for BAKLOG Windows beta (unsigned).
; Compile via packaging/build_windows.ps1 or:
;   ISCC.exe /DAppVersion=0.8.0-beta.1 packaging\baklog.iss

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

#define MyAppName "BAKLOG"
#define MyAppPublisher "BAKLOG"
#define MyAppURL "https://baklog.app"

[Setup]
AppId={{A7B3C9D1-E4F2-4A8B-9C0D-1E2F3A4B5C6D}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\BAKLOG
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=BAKLOG-v{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile=installer-welcome.txt
UninstallDisplayIcon={app}\BAKLOG Tray.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\release\BAKLOG\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\BAKLOG Tray.exe"; Comment: "Open BAKLOG (system tray)"
Name: "{group}\{#MyAppName} (server console)"; Filename: "{app}\BAKLOG.exe"; Comment: "BAKLOG server with console window"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\BAKLOG Tray.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BAKLOG Tray.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
