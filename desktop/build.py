"""Gera o app de desktop do Sealoader para o sistema atual.

    python desktop/build.py            → dist/Sealoader-<sistema>.<ext>

Linux → AppImage · Windows → instalador (Inno Setup) · Mac → .dmg
O GitHub Actions roda este mesmo script em cada sistema (.github/workflows/release.yml).
"""
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build')
DIST = os.path.join(ROOT, 'dist')
TOOLS = os.path.join(BUILD, 'tools')
SYSTEM = {'linux': 'linux', 'win32': 'windows', 'darwin': 'mac'}[sys.platform]
ARCH = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
VERSION = os.environ.get('SEALOADER_VERSION', '1.0.0').lstrip('v')

FFMPEG = {
    ('linux', 'x64'): 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz',
    ('windows', 'x64'): 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip',
    ('mac', 'arm64'): 'https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/{}.zip',
    ('mac', 'x64'): 'https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/{}.zip',
}
DENO = {
    ('linux', 'x64'): 'deno-x86_64-unknown-linux-gnu.zip',
    ('windows', 'x64'): 'deno-x86_64-pc-windows-msvc.zip',
    ('mac', 'arm64'): 'deno-aarch64-apple-darwin.zip',
    ('mac', 'x64'): 'deno-x86_64-apple-darwin.zip',
}
EXE = '.exe' if SYSTEM == 'windows' else ''


def fetch(url):
    print(f'  baixando {url}', flush=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'sealoader-build'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def keep(name, data):
    path = os.path.join(TOOLS, name)
    with open(path, 'wb') as f:
        f.write(data)
    os.chmod(path, 0o755)


def get_tools():
    os.makedirs(TOOLS, exist_ok=True)
    want = [f'ffmpeg{EXE}', f'ffprobe{EXE}', f'deno{EXE}']
    if all(os.path.isfile(os.path.join(TOOLS, w)) for w in want):
        return
    key = (SYSTEM, ARCH)
    url = FFMPEG[key]
    if SYSTEM == 'mac':
        for tool in ('ffmpeg', 'ffprobe'):
            with zipfile.ZipFile(io.BytesIO(fetch(url.format(tool)))) as z:
                keep(tool, z.read(next(n for n in z.namelist() if n.split('/')[-1] == tool)))
    elif url.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(fetch(url))) as z:
            for tool in ('ffmpeg', 'ffprobe'):
                keep(tool + EXE, z.read(next(n for n in z.namelist() if n.endswith(f'/bin/{tool}{EXE}'))))
    else:
        with tarfile.open(fileobj=io.BytesIO(fetch(url)), mode='r:xz') as t:
            for tool in ('ffmpeg', 'ffprobe'):
                m = next(m for m in t.getmembers() if m.name.endswith(f'/bin/{tool}'))
                keep(tool, t.extractfile(m).read())
    with zipfile.ZipFile(io.BytesIO(fetch('https://github.com/denoland/deno/releases/latest/download/' + DENO[key]))) as z:
        keep(f'deno{EXE}', z.read(f'deno{EXE}'))


def pyinstaller():
    sep = os.pathsep
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--name', 'Sealoader',
           '--distpath', os.path.join(BUILD, 'pyi-dist'), '--workpath', os.path.join(BUILD, 'pyi-work'),
           '--specpath', BUILD, '--paths', ROOT,
           '--icon', os.path.join(ROOT, 'web', 'icon-512.png'),
           '--add-data', f'{os.path.join(ROOT, "web")}{sep}web',
           '--add-data', f'{TOOLS}{sep}tools',
           '--hidden-import', 'server',
           '--collect-submodules', 'yt_dlp', '--collect-data', 'yt_dlp_ejs', '--collect-all', 'curl_cffi',
           '--collect-data', 'certifi']
    if SYSTEM in ('windows', 'mac'):
        cmd.append('--windowed')
    if SYSTEM == 'mac':
        cmd += ['--osx-bundle-identifier', 'io.github.opaulovina.sealoader']
    cmd.append(os.path.join(ROOT, 'desktop', 'app.py'))
    subprocess.run(cmd, check=True)
    return os.path.join(BUILD, 'pyi-dist')


def package_linux(out):
    appdir = os.path.join(BUILD, 'Sealoader.AppDir')
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(os.path.join(out, 'Sealoader'), os.path.join(appdir, 'usr', 'lib', 'sealoader'))
    with open(os.path.join(appdir, 'AppRun'), 'w') as f:
        f.write('#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/lib/sealoader/Sealoader" "$@"\n')
    os.chmod(os.path.join(appdir, 'AppRun'), 0o755)
    with open(os.path.join(appdir, 'sealoader.desktop'), 'w') as f:
        f.write('[Desktop Entry]\nType=Application\nName=Sealoader\nComment=Baixe vídeos e gere QR codes\n'
                'Exec=Sealoader\nIcon=sealoader\nCategories=Network;AudioVideo;Utility;\nTerminal=false\n')
    shutil.copy(os.path.join(ROOT, 'web', 'icon.svg'), os.path.join(appdir, 'sealoader.svg'))
    shutil.copy(os.path.join(ROOT, 'web', 'icon-512.png'), os.path.join(appdir, '.DirIcon'))
    tool = os.path.join(BUILD, 'appimagetool')
    if not os.path.isfile(tool):
        with open(tool, 'wb') as f:
            f.write(fetch('https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage'))
        os.chmod(tool, 0o755)
    target = os.path.join(DIST, 'Sealoader-Linux-x86_64.AppImage')
    subprocess.run([tool, '--appimage-extract-and-run', '--no-appstream', appdir, target], check=True,
                   env={**os.environ, 'ARCH': 'x86_64'})
    return target


def package_windows(out):
    iss = os.path.join(ROOT, 'desktop', 'installer.iss')
    iscc = shutil.which('iscc') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    subprocess.run([iscc, f'/DSrcDir={os.path.join(out, "Sealoader")}', f'/DOutDir={DIST}', f'/DAppVer={VERSION}',
                    f'/DIconFile={os.path.join(BUILD, "Sealoader.ico")}', iss], check=True)
    return os.path.join(DIST, 'Sealoader-Windows-Setup.exe')


def package_mac(out):
    name = 'Sealoader-Mac-AppleSilicon.dmg' if ARCH == 'arm64' else 'Sealoader-Mac-Intel.dmg'
    stage = os.path.join(BUILD, 'dmg')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    subprocess.run(['ditto', os.path.join(out, 'Sealoader.app'), os.path.join(stage, 'Sealoader.app')], check=True)
    os.symlink('/Applications', os.path.join(stage, 'Aplicativos'))
    target = os.path.join(DIST, name)
    subprocess.run(['hdiutil', 'create', '-volname', 'Sealoader', '-srcfolder', stage, '-ov', '-format', 'UDZO', target], check=True)
    return target


def make_ico():
    from PIL import Image
    Image.open(os.path.join(ROOT, 'web', 'icon-512.png')).save(
        os.path.join(BUILD, 'Sealoader.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == '__main__':
    os.makedirs(DIST, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    print(f'→ {SYSTEM} {ARCH}', flush=True)
    get_tools()
    make_ico()
    out = pyinstaller()
    result = {'linux': package_linux, 'windows': package_windows, 'mac': package_mac}[SYSTEM](out)
    print(f'✓ {result}', flush=True)
