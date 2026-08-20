; Faceless Studio installer (Inno Setup 6)
; Build the app first with build_app.ps1, then run:  iscc installer.iss

#define AppName "Faceless Studio"
#define AppVersion "2.0.0"
#define AppExeName "FacelessStudio.exe"

[Setup]
AppId={{8F6E2C4A-1B4D-4C9A-9E2D-7A3C5B9D1F0E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Faceless Automation
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=dist
OutputBaseFilename=FacelessStudio-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
WizardStyle=modern
; Icon (optional)
SetupIconFile=assets\faceless.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\FacelessStudio\*"; DestDir: "{app}"; Flags: recursesubdirs
Source: "assets\faceless.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\generator\output"
Type: filesandordirs; Name: "{app}\clipper\output"