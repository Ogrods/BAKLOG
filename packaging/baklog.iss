; Inno Setup script for BAKLOG Windows beta (unsigned).
; Compile via packaging/build_windows.ps1 or:
;   ISCC.exe /DAppVersion=0.8.15 packaging\baklog.iss

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
OutputBaseFilename=BAKLOG-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=installer-icon.ico
WizardImageFile=installer-wizard-large.bmp
WizardSmallImageFile=installer-wizard-small.bmp
InfoBeforeFile=installer-welcome.txt
UninstallDisplayIcon={app}\BAKLOG.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Dirs]
Name: "{localappdata}\BAKLOG-Data"; Permissions: users-full

[Files]
Source: "..\release\BAKLOG\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "BAKLOG.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\BAKLOG Tray.exe"; IconFilename: "{app}\BAKLOG.ico"; Comment: "Open BAKLOG (system tray)"
Name: "{group}\{#MyAppName} (server console)"; Filename: "{app}\BAKLOG.exe"; IconFilename: "{app}\BAKLOG.ico"; Comment: "BAKLOG server with console window"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\BAKLOG.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\BAKLOG Tray.exe"; IconFilename: "{app}\BAKLOG.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\BAKLOG Tray.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  UninstallDataPage: TInputOptionWizardPage;
  DataDirFinishPage: TWizardPage;
  WipeUserData: Boolean;
  CleanupRan: Boolean;

procedure InitializeWizard();
var
  DataDir: string;
begin
  DataDir := ExpandConstant('{localappdata}\BAKLOG-Data');
  DataDirFinishPage := CreateOutputMsgPage(
    wpFinished,
    'Your library folder',
    'Where BAKLOG stores your data',
    'Your games, profiles, and saved connections live separately from the app:' + #13#10 + #13#10 +
    DataDir + #13#10 + #13#10 +
    'App files:' + #13#10 +
    ExpandConstant('{app}') + #13#10 + #13#10 +
    'Before a full uninstall later, open Connections and use Export bundle to back up your sign-ins.',
    True,
    True);
end;

function InitializeUninstall(): Boolean;
var
  DataDir: string;
begin
  Result := True;
  WipeUserData := False;
  CleanupRan := False;
  DataDir := ExpandConstant('{localappdata}\BAKLOG-Data');
  UninstallDataPage := CreateInputOptionPage(
    uwUninstall,
    'Library data',
    'Choose what to remove',
    'The BAKLOG app will be removed from your PC.' + #13#10 + #13#10 +
    'Your library, profiles, and saved connections live in:' + #13#10 +
    DataDir + #13#10 + #13#10 +
    'To back up sign-ins first: open BAKLOG, Connections, Export bundle.',
    True,
    False);
  UninstallDataPage.Add('Keep my library and connections (remove the app only)');
  UninstallDataPage.Add('Remove everything, including library data and saved sign-ins');
  UninstallDataPage.SelectedValueIndex := 0;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = UninstallDataPage.ID then
  begin
    WipeUserData := (UninstallDataPage.SelectedValueIndex = 1);
    if WipeUserData then
    begin
      if MsgBox(
        'Export a backup first? In BAKLOG open Connections, then Export bundle. ' +
        'That saves your store sign-ins to an encrypted file.' + #13#10 + #13#10 +
        'Remove everything anyway?',
        mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure RunUninstallCleanup();
var
  TrayExe: string;
  ResultCode: Integer;
  Args: string;
begin
  if CleanupRan then
    Exit;
  CleanupRan := True;
  Exec('taskkill.exe', '/IM "BAKLOG Tray.exe" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM BAKLOG.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  TrayExe := ExpandConstant('{app}\BAKLOG Tray.exe');
  if not FileExists(TrayExe) then
    Exit;
  if WipeUserData then
    Args := '--uninstall-wipe-user-data'
  else
    Args := '--uninstall-cleanup';
  Exec(TrayExe, Args, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usUninstall then
    RunUninstallCleanup()
  else if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\BAKLOG-Data');
    if WipeUserData then
      MsgBox(
        'BAKLOG and all local data were removed from your PC.' + #13#10 + #13#10 +
        'Browser site data for http://127.0.0.1:8765 may still exist in Chrome or Edge. ' +
        'Clear it from browser settings if you want a fully clean slate.',
        mbInformation, MB_OK)
    else
      MsgBox(
        'BAKLOG was removed from your PC.' + #13#10 + #13#10 +
        'Your library and connections are still in:' + #13#10 +
        DataDir + #13#10 + #13#10 +
        'Reinstall BAKLOG anytime to pick up where you left off.',
        mbInformation, MB_OK);
  end;
end;
