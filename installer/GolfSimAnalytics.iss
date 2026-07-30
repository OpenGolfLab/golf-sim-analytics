; Inno Setup script for Golf Sim Analytics.
;
; Produces a single Setup.exe that installs one-click, no-wizard style --
; like Discord/Slack/Chrome: double-click, a progress bar runs for a few
; seconds, the app launches. No Welcome/Directory/Ready/Finished pages,
; no "Next" clicks. Installs per-user (no admin rights, no UAC prompt)
; into %LocalAppData%\GolfSimAnalytics, which matters for this app
; specifically: it stores its data (raw_csvs\, parquet_data\, logs\) in a
; folder next to its own exe (see config.py's _resolve_base_dir), and
; %LocalAppData% is always writable by the current user -- unlike
; C:\Program Files, which would need an admin-elevated, all-users install
; and a code change to relocate data storage. This keeps the installed
; app byte-for-byte the same as the portable dist\ build_exe.bat already
; produces.
;
; Build first with build_exe.bat (produces dist\), then compile this
; script with ISCC.exe (Inno Setup's command-line compiler) or open it
; in the Inno Setup IDE and press Compile. Output lands in
; installer\Output\GolfSimAnalytics-Setup.exe.

#define MyAppName "Golf Sim Analytics"
#define MyAppPublisher "Golf Sim Analytics"
#define MyAppExeName "GolfSimAnalytics.exe"

; The installed version -- what Add/Remove Programs lists -- is read out of
; config.py's APP_VERSION at compile time, so there is exactly one number to
; bump at release time (RELEASING.md phase 1) and no way for the installer to
; disagree with the app it installs. It was hard-coded here instead, and had
; read "1.0.0" since the first release: every build through v1.4.0 installed
; itself as 1.0.0 no matter what the app reported in Settings.
;
; Parsed by the preprocessor rather than passed in on the ISCC command line,
; so it works both ways this script gets compiled -- build_installer.bat, and
; opening it in the Inno Setup IDE (see the header note above).
; SourcePath (this script's own folder) rather than a bare relative path: the
; preprocessor's FileOpen resolves against the current working directory, not
; the script, so "..\config.py" finds nothing when ISCC is invoked from the
; repo root -- which is exactly how build_installer.bat invokes it.
#define ConfigFile AddBackslash(SourcePath) + "..\config.py"
#define MyAppVersion
#define ConfigHandle
#define ConfigLine

#sub ReadAppVersion
  #define ConfigLine FileRead(ConfigHandle)
  #if (Pos("APP_VERSION", ConfigLine) == 1) && (Pos('"', ConfigLine) > 0)
    ; "public" is required, not decoration: a #define inside a #sub is local
    ; to that sub, so without it the version is found and then discarded when
    ; the sub returns -- and the #error below fires on a config.py that was
    ; parsed perfectly well.
    #define public MyAppVersion \
      Copy(ConfigLine, Pos('"', ConfigLine) + 1, \
           RPos('"', ConfigLine) - Pos('"', ConfigLine) - 1)
  #endif
#endsub

#for {ConfigHandle = FileOpen(ConfigFile); \
      ConfigHandle && !FileEof(ConfigHandle); ""} ReadAppVersion
#expr FileClose(ConfigHandle)

; Fail the build rather than guess. An installer labelled with a version it
; isn't is the exact bug being fixed here, and it's invisible until someone
; opens Add/Remove Programs months later.
#if MyAppVersion == ""
  #error Could not read APP_VERSION from config.py -- refusing to build a mislabelled installer.
#endif

[Setup]
; Fixed AppId so re-running a newer installer upgrades in place instead
; of creating a second entry in Add/Remove Programs.
AppId={{A47B4904-5CDB-437D-80A6-2B95AAF000F5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\GolfSimAnalytics
DefaultGroupName={#MyAppName}
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
; --- One-click install: no wizard pages, no decisions to make ---
; Directory is always %LocalAppData%\GolfSimAnalytics (no admin needed and
; no reason for a user to ever pick a different one), the Start Menu
; group name never varies, and there's nothing to confirm before
; installing or after it finishes. Skipping all five pages leaves just
; a short "Installing..." progress bar between double-click and launch.
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableReadyMemo=yes
DisableFinishedPage=yes
; Upgrading while the app is open is the NORMAL path (the in-app update
; notice sends people here with the app running), so don't stop to ask about
; it: force closes the running app gracefully (WM_CLOSE via Restart Manager,
; not a kill) instead of showing the "applications using files" page. Restart
; is left to the [Run] entry below — with RestartApplications on, Restart
; Manager could relaunch the old exe mid-install and re-lock the very file
; being replaced (seen in the wild on the v1.5.0 rollout), and a successful
; install would end with two copies open.
CloseApplications=force
RestartApplications=no
; Everything the app needs is bundled in dist\ (built by build_exe.bat);
; nothing else on the target machine is required.
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Pulls in everything build_exe.bat staged next to the exe -- the exe
; itself, the course photo, and both sample datasets -- so the installed
; app looks exactly like running "python app.py" from the source repo.
; Excludes are belt-and-braces on top of build_exe.bat's dist\ clean: the
; app stores user data (raw_csvs\, parquet_data\, logs\, settings.json)
; next to the exe, so if dist\ is ever dirty from a test run, packaging
; those paths would overwrite every user's settings and inject the
; developer's sessions into their data on upgrade. Never ship them.
;
; .contributor_id is the worst of them and the least obvious, because it
; isn't visible in a folder listing: it's the locked, write-once id the
; community aggregate de-duplicates on (see contribute.py). Shipping one
; would hand every installation the SAME identity -- the whole community
; would aggregate as a single golfer, and no user could ever be issued a
; new id, because a valid id is never overwritten. .contribute_consent
; goes with it: consent is something each user gives, never something an
; installer can arrive having already granted on their behalf.
Source: "..\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "raw_csvs\*,parquet_data\*,logs\*,settings.json,.contributor_id,.contribute_consent"

[Icons]
; No Tasks page to opt into these (it was the last remaining wizard
; page), so both shortcuts are just always created -- that's what a
; one-click installer's Start Menu / Desktop shortcuts do anyway.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
; With the Finished page disabled there's no checkbox for this -- Setup
; launches the app automatically the moment install completes.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifsilent
