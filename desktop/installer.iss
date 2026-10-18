; Instalador do Sealoader para Windows (Inno Setup 6). Gerado por desktop/build.py.
#ifndef Ver
  #define Ver "1.0.0"
#endif
[Setup]
AppId={{6F1E2B7A-5C1D-4C8E-9C1A-5EA10ADE0001}
AppName=Sealoader
AppVersion={#Ver}
AppPublisher=Paulo Vinícius
DefaultDirName={localappdata}\Programs\Sealoader
DefaultGroupName=Sealoader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Out}
OutputBaseFilename=Sealoader-Windows-Setup
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\Sealoader.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Sealoader"; Filename: "{app}\Sealoader.exe"
Name: "{autodesktop}\Sealoader"; Filename: "{app}\Sealoader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Sealoader.exe"; Description: "Abrir o Sealoader agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM Sealoader.exe /F"; Flags: runhidden; RunOnceId: "KillSealoader"
