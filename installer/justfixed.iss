; JustFixed Inno Setup installer script
;
; Compile from repo root:
;   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\justfixed.iss
;
; Output: dist\JustFixed-Setup-{version}.exe
;
; CRITICAL: AppId is a stable GUID that must never change between releases.
; Each unique AppId is treated by Windows as a separate product — changing
; it means upgrades stop working and old installs become unremovable orphans.
; The GUID below was generated once and is permanently pinned to this product.
;
; Data directory: {%USERPROFILE%}\.justfixed\
; The installer writes ONLY to the install dir ({app}).
; It never references, touches, or removes the user data directory.
; Uninstall removes only what the installer wrote.

#define AppVersion "0.1.0"

[Setup]
AppId={{B3CAA8BC-1602-47AA-996E-96198F7FAD47}}
AppName=JustFixed
AppVersion={#AppVersion}
AppPublisher=JustFixed (placeholder — developer can edit later)
DefaultDirName={localappdata}\Programs\JustFixed
DefaultGroupName=JustFixed
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=JustFixed-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\JustFixed.exe
UninstallDisplayName=JustFixed

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkablealone
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\JustFixed\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JustFixed"; Filename: "{app}\JustFixed.exe"; Tasks: startmenuicon
Name: "{group}\Uninstall JustFixed"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{userdesktop}\JustFixed"; Filename: "{app}\JustFixed.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\JustFixed.exe"; Description: "Launch JustFixed"; Flags: nowait postinstall skipifsilent
