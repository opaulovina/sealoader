"""Sealoader para desktop (Windows, Mac, Linux).

Sobe o mesmo server.py localmente, sem senha, abre o navegador e fecha sozinho alguns
minutos depois que a última aba do Sealoader for fechada. Tudo roda no próprio computador:
yt-dlp, ffmpeg e deno vão dentro do app, e o yt-dlp se atualiza sozinho (os sites mudam muito).

    python desktop/app.py [--no-browser] [--port N]
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
import zipimport

FROZEN = getattr(sys, 'frozen', False)
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = '.exe' if os.name == 'nt' else ''


def data_dir():
    if os.name == 'nt':
        root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        root = os.path.expanduser('~/Library/Application Support')
    else:
        root = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    path = os.path.join(root, 'Sealoader')
    os.makedirs(path, exist_ok=True)
    return path


DATA = data_dir()
YTDLP_ZIP = os.path.join(DATA, 'yt-dlp.zip')

# windowed apps (Windows/Mac) have no console: keep a log file instead
if FROZEN or sys.stdout is None:
    log = open(os.path.join(DATA, 'sealoader.log'), 'a', buffering=1, encoding='utf-8')
    sys.stdout = sys.stderr = log

try:
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
except ImportError:
    pass

tools = os.path.join(BASE, 'tools')
os.environ.update(SEALOADER_DESKTOP='1', SEALOADER_DATA=DATA, SEALOADER_WEB=os.path.join(BASE, 'web'))
if os.path.isfile(os.path.join(tools, 'ffmpeg' + EXE)):
    os.environ['SEALOADER_FFMPEG'] = tools
    os.environ['PATH'] = tools + os.pathsep + os.environ.get('PATH', '')
if os.path.isfile(os.path.join(tools, 'deno' + EXE)):
    os.environ['SEALOADER_DENO'] = os.path.join(tools, 'deno' + EXE)


class _UpdatedYtDlp:
    """Import yt_dlp from the downloaded yt-dlp.zip instead of the copy frozen inside the app."""

    def find_spec(self, name, path=None, target=None):
        if name == 'yt_dlp':
            return zipimport.zipimporter(YTDLP_ZIP).find_spec(name)
        if name.startswith('yt_dlp.') and path:
            for p in path:
                if p.startswith(YTDLP_ZIP):
                    return zipimport.zipimporter(p).find_spec(name)
        return None


def use_updated_ytdlp():
    if not os.path.isfile(YTDLP_ZIP):
        return
    finder = _UpdatedYtDlp()
    sys.meta_path.insert(0, finder)
    try:
        import importlib
        importlib.import_module('yt_dlp.YoutubeDL')
    except Exception as e:  # noqa: BLE001  broken update: forget it, use the bundled one
        print(f'yt-dlp atualizado falhou ({e}); usando o embutido', flush=True)
        sys.meta_path.remove(finder)
        for mod in [m for m in sys.modules if m == 'yt_dlp' or m.startswith('yt_dlp.')]:
            del sys.modules[mod]
        os.remove(YTDLP_ZIP)


def update_ytdlp(current):
    state_path = os.path.join(DATA, 'update.json')
    try:
        state = json.load(open(state_path))
    except (OSError, ValueError):
        state = {}
    if time.time() - state.get('checked', 0) < 24 * 3600:
        return
    try:
        req = urllib.request.Request('https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest',
                                     headers={'User-Agent': 'sealoader', 'Accept': 'application/vnd.github+json'})
        rel = json.load(urllib.request.urlopen(req, timeout=20))
        tag = rel['tag_name']
        if tag != current:
            asset = next(a for a in rel['assets'] if a['name'] == 'yt-dlp')
            tmp = YTDLP_ZIP + '.tmp'
            urllib.request.urlretrieve(asset['browser_download_url'], tmp)
            with zipfile.ZipFile(tmp) as z:
                if 'yt_dlp/__init__.py' not in z.namelist():
                    raise ValueError('arquivo do yt-dlp inválido')
            os.replace(tmp, YTDLP_ZIP)
            print(f'yt-dlp {tag} baixado; vale na próxima abertura', flush=True)
        json.dump({'checked': time.time(), 'tag': tag}, open(state_path, 'w'))
    except Exception as e:  # noqa: BLE001
        print(f'não deu para checar atualização do yt-dlp: {e}', flush=True)


def running_sealoader(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/version', timeout=1.5) as r:
            return json.load(r).get('app') == 'sealoader'
    except Exception:  # noqa: BLE001
        return False


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def main():
    args = sys.argv[1:]
    port = int(args[args.index('--port') + 1]) if '--port' in args else 8765
    browser = '--no-browser' not in args
    url = f'http://127.0.0.1:{port}/'

    # already open (or the home server on this same PC)? just show it
    if running_sealoader(port):
        if browser:
            webbrowser.open(url)
        return
    if not port_free(port):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        url = f'http://127.0.0.1:{port}/'

    use_updated_ytdlp()
    sys.path.insert(0, BASE)
    import server
    import yt_dlp
    threading.Thread(target=update_ytdlp, args=(yt_dlp.version.__version__,), daemon=True).start()

    if browser:
        def open_when_ready():
            for _ in range(100):
                if running_sealoader(port):
                    webbrowser.open(url)
                    return
                time.sleep(0.1)
        threading.Thread(target=open_when_ready, daemon=True).start()
    server.serve(port)


if __name__ == '__main__':
    main()
