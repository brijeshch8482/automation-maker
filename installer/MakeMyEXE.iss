; MakeMyEXE per-user installer (docs/DESKTOP_APP.md §9). Built by `python -m build.installer
; make` on windows-latest (.github/workflows/release.yml), which passes:
;   /DAppVersion=1.0.0  /DRunnerDir=<the Runner folder>  /DPreinstalledDir=<signed .mmx files>
;   /DOutputDir=<folder>
;
; - Per user, no admin, no UAC: %LOCALAPPDATA%\Programs\MakeMyEXE. Registry: HKCU only.
; - The .mmx file association opens `MakeMyEXE.exe --import "<file>"`.
; - Start menu: MakeMyEXE (the Hub). The app adds one entry per automation in the same folder.
; - Upgrade in place keeps the store (%LOCALAPPDATA%\MakeMyEXE), settings and install.json.
; - Uninstall removes the app and its Start menu folder, then asks whether to remove the
;   automations and their settings too; the default is Keep. Files the user made with the
;   automations are never touched.

#ifndef AppVersion
  #error Pass /DAppVersion=<x.y.z>
#endif

[Setup]
AppId={{6F1E3B52-8A0D-4E7C-9B1A-4D2C5E7F8A90}
AppName=MakeMyEXE
AppVersion={#AppVersion}
AppVerName=MakeMyEXE {#AppVersion}
AppPublisher=MakeMyEXE
AppPublisherURL=https://makemyexe.pages.dev
DefaultDirName={userpf}\MakeMyEXE
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesAssociations=yes
CloseApplications=yes
UninstallDisplayIcon={app}\MakeMyEXE.exe
UninstallDisplayName=MakeMyEXE
OutputDir={#OutputDir}
OutputBaseFilename=MakeMyEXE-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#RunnerDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PreinstalledDir}\*.mmx"; DestDir: "{app}\preinstalled"; Flags: ignoreversion

[InstallDelete]
; An upgrade brings its own free set; an automation already added stays in the store.
Type: filesandordirs; Name: "{app}\preinstalled"
Type: filesandordirs; Name: "{app}\_internal"

[Registry]
Root: HKCU; Subkey: "Software\Classes\.mmx"; ValueType: string; ValueName: ""; ValueData: "MakeMyEXE.Bundle"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\MakeMyEXE.Bundle"; ValueType: string; ValueName: ""; ValueData: "MakeMyEXE automation"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\MakeMyEXE.Bundle\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\MakeMyEXE.exe,0"
Root: HKCU; Subkey: "Software\Classes\MakeMyEXE.Bundle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MakeMyEXE.exe"" --import ""%1"""

[Icons]
Name: "{userprograms}\MakeMyEXE\MakeMyEXE"; Filename: "{app}\MakeMyEXE.exe"; Comment: "Your automations"

[Run]
Filename: "{app}\MakeMyEXE.exe"; Description: "Open MakeMyEXE"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Our Start menu folder, with the entries the app made for each automation.
Type: filesandordirs; Name: "{userprograms}\MakeMyEXE"
; Not {app} as a whole: Inno removes the files it installed, and nothing else may go.

[Code]
function RemoveStoreAsked(): Boolean;
begin
  { /REMOVESTORE answers yes without asking (the uninstall check in CI uses it). }
  if Pos('/REMOVESTORE', Uppercase(GetCmdTail())) > 0 then
    Result := True
  else
    Result := SuppressibleMsgBox(
      'Also remove your automations and their settings?' + #13#10 + #13#10 +
      'Files you made with them (PDFs, invoices, renamed files) are never removed.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if RemoveStoreAsked() then
    begin
      { Only our own folders: the store and each automation's settings. }
      DelTree(ExpandConstant('{localappdata}\MakeMyEXE'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\MakeMyEXE'), True, True, True);
    end;
end;
