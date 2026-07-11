; Inno Setup script for Golf Sim Analytics.
;
; Produces a single Setup.exe with a normal Windows install wizard --
; no command line involved for the end user. Installs per-user (no admin
; rights, no UAC prompt) into %LocalAppData%\GolfSimAnalytics, which
; matters for this app specifically: it stores its data (raw_csvs\,
; parquet_data\, logs\) in a folder next to its own exe (see
; config.py's _resolve_base_dir), and %LocalAppData% is always writable
; by the current user -- unlike C:\Program Files, which would need an
; admin-elevated, all-users install and a code change to relocate data
; storage. This keeps the installed app byte-for-byte the same as the
; portable dist\ build_exe.bat already produces.
;
; Build first with build_exe.bat (produces dist\), then compile this
; script with ISCC.exe (Inno Setup's command-line compiler) or open it
; in the Inno Setup IDE and press Compile. Output lands in
; installer\Output\GolfSimAnalytics-Setup.exe.

#define MyAppName "Golf Sim Analytics"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Golf Sim Analytics"
#define MyAppExeName "GolfSimAnalytics.exe"

[Setup]
; Fixed AppId so re-running a newer installer upgrades in place instead
; of creating a second entry in Add/Remove Programs.
AppId={{A47B4904-5CDB-437D-80A6-2B95AAF000F5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\GolfSimAnalytics
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no admin rights required, no UAC prompt. A user can
; still right-click "Run as administrator" if they want an all-users
; install, but nothing forces it.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=GolfSimAnalytics-Setup
SetupIconFile=..\assets\icon.ico
; Without these, Windows' "Apps & Features" list shows a generic icon and
; appends the version to the name for this entry (defaults are cosmetically
; rough, not wrong) -- set explicitly for a clean Add/Remove Programs listing.
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Everything the app needs is bundled in dist\ (built by build_exe.bat);
; nothing else on the target machine is required.
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Pulls in everything build_exe.bat staged next to the exe -- the exe
; itself, the course photo, and both sample datasets -- so the installed
; app looks exactly like running "python app.py" from the source repo.
Source: "..\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
