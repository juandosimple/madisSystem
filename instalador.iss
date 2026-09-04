; Instalador para Windows. Lo compila ISCC.exe (Inno Setup 6) en el workflow.
#define Nombre    "Expedientes GEDO"
#define Version   "1.0.0"
#define Ejecutable "ExpedientesGEDO.exe"

[Setup]
AppName={#Nombre}
AppVersion={#Version}
AppPublisher=IFTS
DefaultDirName={autopf}\ExpedientesGEDO
DefaultGroupName={#Nombre}
; permite instalar sin ser administrador: en las escuelas rara vez se tiene
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=salida
OutputBaseFilename=ExpedientesGEDO-{#Version}-instalador
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; 'x64compatible' requiere Inno 6.3+; 'x64' funciona en toda la serie 6
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; \
  GroupDescription: "Accesos directos:"

[Files]
Source: "dist\ExpedientesGEDO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\{#Ejecutable}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\{#Ejecutable}"; Tasks: escritorio

[Run]
Filename: "{app}\{#Ejecutable}"; Description: "Abrir {#Nombre}"; \
  Flags: nowait postinstall skipifsilent
