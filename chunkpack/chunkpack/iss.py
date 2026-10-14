"""Renders the Inno Setup 6 script for a chunked package."""
import re
import uuid
from pathlib import Path, PureWindowsPath

from .chunker import PackedFile
from .manifest import Manifest

# Fixed for all packages. before_install/after_install keep GOG's names and
# argument order, so tools that understand GOG installers can read ours too.
CODE = r"""
[Code]
function MergeParts(Parts, Dest, FileMd5: String): Integer;
  external 'MergeParts@files:chunkhelper.dll stdcall';

var
  CurRelPath, CurFileMd5, CurParts, FailText: String;
  CurPartsLeft: Integer;
  NewFiles: TStringList;  // merged files that did not exist before, for rollback
  InstallFinished: Boolean;

function InitializeSetup: Boolean;
begin
  NewFiles := TStringList.Create;
  Result := True;
end;

procedure InitializeWizard;
begin
  // Inno would show the temp part names; before_install shows the real file instead.
  WizardForm.FilenameLabel.Visible := False;
end;

procedure before_install(FileMd5, RelPath: String; PartCount: Integer);
begin
  CurFileMd5 := FileMd5;
  CurRelPath := RelPath;
  CurPartsLeft := PartCount;
  CurParts := '';
  FailText := '';
  WizardForm.StatusLabel.Caption := RelPath;
end;

// No '?', ':' or '*': the text ends up in a file name (see MergeFailure).
function MergeErrorText(Code: Integer): String;
begin
  case Code of
    2: Result := 'a part could not be opened';
    3: Result := 'a part could not be read';
    4: Result := 'a part is not valid zlib data';
    5: Result := 'a part has the wrong size';
    6: Result := 'a part failed its MD5 check';
    7: Result := 'the file could not be created';
    8: Result := 'the file could not be written - the disk may be full';
    9: Result := 'the file failed its MD5 check';
    10: Result := 'the file could not be replaced - it may be in use';
    11: Result := 'out of memory';
  else
    Result := 'error ' + IntToStr(Code);
  end;
end;

procedure after_install(PartMd5: String; CompressedSize, Size: Integer);
var
  Dest: String;
  Code: Integer;
  Existed: Boolean;
begin
  CurParts := CurParts + ExpandConstant(CurrentFileName) + '|' + IntToStr(Size) + '|' + PartMd5 + #10;
  CurPartsLeft := CurPartsLeft - 1;
  if CurPartsLeft > 0 then
    Exit;
  Dest := ExpandConstant('{app}') + '\' + CurRelPath;
  Existed := FileExists(Dest);
  if ForceDirectories(ExtractFileDir(Dest)) then
    Code := MergeParts(CurParts, Dest, CurFileMd5)
  else
    Code := 7;
  CurParts := '';
  if Code = 0 then begin
    if not Existed then
      NewFiles.Add(Dest);
  end else begin
    FailText := 'Could not unpack ' + CurRelPath + ' (' + MergeErrorText(Code) + ')';
    Log(FailText);
  end;
end;

// Hook exceptions do not stop Inno, so a failed merge enables the entry that
// follows the file's parts. Its source is deliberately missing and named after
// the failure: Inno then shows its own Abort/Retry/Ignore error, and Abort
// (the default when silent) rolls the installation back.
function MergeFailed: Boolean;
begin
  Result := FailText <> '';
end;

function MergeFailure(Param: String): String;
begin
  Result := FailText;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallFinished := True;
end;

// Inno's rollback only knows the files it wrote itself; remove ours too.
procedure DeinitializeSetup;
var
  I: Integer;
  App, Dir: String;
begin
  if InstallFinished or (NewFiles = nil) or (NewFiles.Count = 0) then
    Exit;
  App := ExpandConstant('{app}');
  for I := NewFiles.Count - 1 downto 0 do begin
    DeleteFile(NewFiles[I]);
    Dir := ExtractFileDir(NewFiles[I]);
    while (Length(Dir) > Length(App)) and RemoveDir(Dir) do
      Dir := ExtractFileDir(Dir);
  end;
  RemoveDir(App);
end;
"""


def q(s: str) -> str:
    """Quotes an Inno parameter value."""
    return '"' + s.replace('"', '""') + '"'


def const(s: str) -> str:
    """Escapes text so Inno does not read it as a {constant}."""
    return s.replace("{", "{{")


def pas(s: str) -> str:
    """Pascal string literal."""
    return "'" + s.replace("'", "''") + "'"


def winpath(p: Path) -> str:
    """Absolute Windows path; under Wine, Z: maps to the Linux root."""
    s = str(p.resolve())
    return s if PureWindowsPath(s).drive else "Z:" + s.replace("/", "\\")


def link_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', " ", name).strip()


def render(m: Manifest, packed: list[PackedFile], empty_dirs: list[str],
           sources: dict[str, Path]) -> str:
    """Part sources are referenced as parts\\ab\\cd\\<md5>, relative to the script."""
    app_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chunkpack:{m.publisher}:{m.id}")).upper()
    total_size = sum(f.size for f in packed)
    stored_size = sum(p.csize for f in packed for p in f.parts)
    exe_dir = str(PureWindowsPath(m.exe).parent)
    workdir = "{app}" if exe_dir == "." else "{app}\\" + const(exe_dir)
    name, link = const(m.name), const(link_name(m.name))

    setup = {
        "AppId": "{{" + app_id + "}",
        "AppName": name,
        "AppVersion": const(m.version),
        "AppPublisher": const(m.publisher),
        "AppPublisherURL": const(m.url),
        "AppSupportURL": const(m.url),
        "DefaultDirName": m.default_dir or "{sd}\\Games\\" + link,
        "DisableProgramGroupPage": "yes",
        "UninstallDisplayName": name,
        "UninstallDisplayIcon": "{app}\\" + const(m.exe),
        "OutputDir": winpath(m.output_dir),
        "OutputBaseFilename": m.basename,
        "DiskSpanning": "yes",
        "SlicesPerDisk": "1",
        "DiskSliceSize": str(m.slice_size),
        "Compression": "lzma2",
        "SolidCompression": "no",
        "WizardStyle": "modern",
        "ArchitecturesInstallIn64BitMode": "x64compatible",
        "PrivilegesRequired": "lowest" if m.per_user else "admin",
        # Inno counts the stored parts; the inflated files need the difference on top.
        "ExtraDiskSpaceRequired": str(max(0, total_size - stored_size)),
        "SetupIconFile": m.icon and winpath(m.icon),
        "LicenseFile": m.license and winpath(m.license),
        "WizardImageFile": m.wizard_image and winpath(m.wizard_image),
        "WizardSmallImageFile": m.wizard_small_image and winpath(m.wizard_small_image),
    }
    out = ["; Generated by chunkpack - edit the manifest, not this file.",
           # Stop the preprocessor treating "{#" in file names as inline directives.
           '#pragma inlinestart "<:chunkpack-inline:"',
           '#pragma inlineend ":chunkpack-inline:>"', "", "[Setup]"]
    out += [f"{k}={v}" for k, v in setup.items() if v]

    out += ["", "[Languages]"]
    for lang in m.languages:
        isl = "compiler:Default.isl" if lang.lower() == "english" else f"compiler:Languages\\{lang}.isl"
        out.append(f"Name: {q(lang.lower())}; MessagesFile: {q(isl)}")

    out += ["", "[CustomMessages]", f"LaunchApp=Launch {m.name}", "",
            "[Tasks]",
            'Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; '
            'GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked']

    if empty_dirs:
        out += ["", "[Dirs]"] + [f"Name: {q('{app}\\' + const(d))}" for d in empty_dirs]

    out += ["", "[Files]", 'Source: "chunkhelper.dll"; Flags: dontcopy']
    for f in packed:
        if not f.parts:  # empty file: nothing to chunk, let Inno create it
            d = str(PureWindowsPath(f.rel).parent)
            out.append(f"Source: {q(winpath(sources[f.rel]))}; "
                       f"DestDir: {q('{app}' if d == '.' else '{app}\\' + const(d))}; "
                       f"DestName: {q(const(PureWindowsPath(f.rel).name))}; Flags: ignoreversion")
            continue
        for i, p in enumerate(f.parts):
            src = Path("parts") / p.md5[:2] / p.md5[2:4] / p.md5
            line = (f"Source: {q(str(PureWindowsPath(src)))}; DestDir: {q('{tmp}\\' + p.md5[:2] + '\\' + p.md5[2:4])}; "
                    "Flags: nocompression ignoreversion deleteafterinstall")
            if i == 0:
                line += f"; BeforeInstall: {q(f'before_install({pas(f.md5)}, {pas(f.rel)}, {len(f.parts)})')}"
            line += f"; AfterInstall: {q(f'after_install({pas(p.umd5)}, {p.csize}, {p.usize})')}"
            out.append(line)
        out.append('Source: "{tmp}\\{code:MergeFailure}"; DestDir: "{tmp}\\failed"; '
                   "Flags: external ignoreversion deleteafterinstall; Check: MergeFailed")

    out += ["", "[Icons]"]
    icon_common = f"Filename: {q('{app}\\' + const(m.exe))}; WorkingDir: {q(workdir)}"
    if m.exe_args:
        icon_common += f"; Parameters: {q(m.exe_args)}"
    out.append(f"Name: {q('{autoprograms}\\' + link)}; {icon_common}")
    out.append(f"Name: {q('{autodesktop}\\' + link)}; {icon_common}; Tasks: desktopicon")

    key = f"Software\\{const(link_name(m.publisher))}\\Games\\{const(m.id)}"
    values = {"path": "{app}", "exe": "{app}\\" + const(m.exe), "launchParam": const(m.exe_args),
              "workingDir": workdir, "gameID": const(m.id), "gameName": name,
              "version": const(m.version), "buildId": const(m.build)}
    out += ["", "[Registry]"]
    for i, (k, v) in enumerate(values.items()):
        flags = "; Flags: uninsdeletekey" if i == 0 else ""
        out.append(f"Root: HKA; Subkey: {q(key)}; ValueType: string; ValueName: {q(k)}; ValueData: {q(v)}{flags}")

    out += ["", "[Run]"]
    for r in m.redists:
        out.append(f"Filename: {q('{app}\\' + const(r.dest))}; Parameters: {q(r.args)}; "
                   f"StatusMsg: {q('Installing ' + const(r.description) + '...')}; Flags: waituntilterminated")
    run = f"Filename: {q('{app}\\' + const(m.exe))}; WorkingDir: {q(workdir)}"
    if m.exe_args:
        run += f"; Parameters: {q(m.exe_args)}"
    out.append(run + '; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent')

    # Merged files are written by our [Code], so Inno's uninstall log does not know them.
    dirs = set()
    for f in packed:
        parent = PureWindowsPath(f.rel).parent
        while str(parent) != ".":
            dirs.add(str(parent))
            parent = parent.parent
    dirs.update(empty_dirs)
    out += ["", "[UninstallDelete]"]
    out += [f"Type: files; Name: {q('{app}\\' + const(f.rel))}" for f in packed if f.parts]
    out += [f"Type: dirifempty; Name: {q('{app}\\' + const(d))}"
            for d in sorted(dirs, key=lambda d: (-d.count("\\"), d))]
    out.append('Type: dirifempty; Name: "{app}"')

    return "\n".join(out) + "\n" + CODE
