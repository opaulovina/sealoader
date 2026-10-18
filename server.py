#!/usr/bin/env python3
"""Sealoader — downloader de vídeos (yt-dlp) + gerador de QR code.

Roda de três jeitos com o mesmo código:
  * servidor da casa  (python server.py)        → atende o site do GitHub Pages, o APK e o iPhone via túnel
  * app de desktop    (desktop/app.py congelado) → tudo local, sem senha, fecha sozinho quando ocioso
  * desenvolvimento   (python server.py)        → http://127.0.0.1:8765
"""
import glob
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from itsdangerous import BadSignature, URLSafeTimedSerializer

import yt_dlp
from yt_dlp.extractor.common import InfoExtractor

HERE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
WEB = os.environ.get('SEALOADER_WEB') or os.path.join(HERE, 'web')
DATA = os.environ.get('SEALOADER_DATA') or os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.environ.get('SEALOADER_DESKTOP') == '1'
PORT = int(os.environ.get('SEALOADER_PORT', 8765))
WORK = os.path.join(tempfile.gettempdir(), 'sealoader-jobs')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
os.makedirs(WORK, exist_ok=True)
os.makedirs(DATA, exist_ok=True)

app = Flask(__name__, static_folder=None)
JOBS = {}

# ---------------------------------------------------------------- config
CONFIG_PATH = os.path.join(DATA, 'config.json')
WORDS = ['mar', 'onda', 'vidro', 'coral', 'areia', 'concha', 'brisa', 'lua', 'sol', 'nuvem', 'farol', 'ilha', 'peixe', 'alga', 'praia']


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    if not cfg.get('password'):
        cfg['password'] = f'{secrets.choice(WORDS)}-{secrets.choice(WORDS)}-{secrets.randbelow(9000) + 1000}'
    cfg.setdefault('secret', secrets.token_hex(32))
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    return cfg


CONFIG = load_config()
SIGNER = URLSafeTimedSerializer(CONFIG['secret'], salt='sealoader-auth')
TOKEN_AGE = 365 * 24 * 3600
FAILS = {}
LAST_PING = [time.time()]


def pages_origin():
    url = CONFIG.get('pages_url') or ''
    parts = urllib.parse.urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}' if parts.netloc else None


def password_tag():
    # tokens die when the password changes
    return hashlib.sha256(CONFIG['password'].lower().encode()).hexdigest()[:16]


def token_ok(tok):
    try:
        return SIGNER.loads(tok, max_age=TOKEN_AGE).get('p') == password_tag()
    except (BadSignature, AttributeError):
        return False


# ---------------------------------------------------------------- access
# Requests that arrive through the tunnel (Cloudflare / Tailscale add these headers)
# need the password token; requests made directly on this PC don't.
def is_remote():
    return any(h in request.headers for h in ('Cf-Ray', 'Cf-Connecting-Ip', 'X-Forwarded-For', 'Tailscale-User-Login')) \
        or request.remote_addr not in ('127.0.0.1', '::1')


def client_ip():
    return request.headers.get('Cf-Connecting-Ip') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() \
        or request.remote_addr


PUBLIC_API = {'/api/login', '/api/version'}


@app.before_request
def guard():
    if request.method == 'OPTIONS':
        return Response(status=204)
    if not request.path.startswith('/api/') or request.path in PUBLIC_API or not is_remote():
        return None
    auth = request.headers.get('Authorization', '')
    tok = auth[7:] if auth.startswith('Bearer ') else request.args.get('t', '')
    if not token_ok(tok):
        return jsonify(error='Faça login novamente', login=True), 401
    return None


@app.after_request
def headers(resp):
    origin = request.headers.get('Origin')
    if origin and origin == pages_origin():
        resp.headers.update({
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Expose-Headers': 'Content-Disposition',
            'Access-Control-Max-Age': '86400',
            'Vary': 'Origin',
        })
    if not request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.post('/api/login')
def api_login():
    ip = client_ip()
    fails, since = FAILS.get(ip, (0, 0))
    if fails >= 5 and time.time() - since < 300:
        return jsonify(error='Muitas tentativas. Espere 5 minutos.'), 429
    pw = str((request.get_json(silent=True) or {}).get('password', '')).strip().lower()
    if hmac.compare_digest(pw.encode(), CONFIG['password'].lower().encode()):
        FAILS.pop(ip, None)
        return jsonify(ok=True, token=SIGNER.dumps({'p': password_tag()}))
    FAILS[ip] = (fails + 1, time.time() if fails == 0 or time.time() - since >= 300 else since)
    time.sleep(1)
    return jsonify(error='Senha incorreta'), 403


def tunnel_url():
    try:
        with urllib.request.urlopen('http://127.0.0.1:20241/quicktunnel', timeout=2) as r:
            host = json.load(r).get('hostname')
            return f'https://{host}' if host else None
    except Exception:  # noqa: BLE001
        return None


@app.get('/api/share')
def api_share():
    if is_remote() or DESKTOP:
        abort(404)
    return jsonify(url=CONFIG.get('pages_url') or tunnel_url(), tunnel=tunnel_url(), password=CONFIG['password'])


@app.post('/api/ping')
def api_ping():
    LAST_PING[0] = time.time()
    return jsonify(ok=True)


# ---------------------------------------------------------------- TokyVideo
class TokyVideoIE(InfoExtractor):
    IE_NAME = 'tokyvideo'
    _VALID_URL = r'https?://(?:www\.)?tokyvideo\.com/(?:[a-z]{2}/)?(?:video|embed)/(?P<id>[^/?#]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id, headers={'User-Agent': UA})
        if 'not available in your country' in webpage:
            self.raise_geo_restricted('O TokyVideo bloqueou este vídeo no seu país')
        formats = []
        for m in re.finditer(r'<source\b[^>]*>', webpage):
            tag = m.group(0)
            src = self._search_regex(r'src=["\']([^"\']+)', tag, 'src', default=None)
            if not src:
                continue
            src = html.unescape(src)
            label = self._search_regex(r'(?:label|res|size)=["\']([^"\']+)', tag, 'label', default=None)
            height = int(re.sub(r'\D', '', label)) if label and re.search(r'\d', label) else None
            if '.m3u8' in src:
                formats.extend(self._extract_m3u8_formats(src, video_id, 'mp4', fatal=False))
            else:
                formats.append({'url': src, 'ext': 'mp4', 'height': height, 'format_id': label or f'mp4-{len(formats)}',
                                'http_headers': {'Referer': url, 'User-Agent': UA}})
        if not formats:
            self.raise_no_formats('Nenhum vídeo encontrado nesta página do TokyVideo', expected=True)
        return {
            'id': video_id,
            'title': self._og_search_title(webpage, default=None) or self._html_extract_title(webpage) or video_id,
            'thumbnail': self._og_search_thumbnail(webpage, default=None)
                         or self._search_regex(r'poster=["\']([^"\']+)', webpage, 'poster', default=None),
            'uploader': self._search_regex(r'class="[^"]*user-name[^"]*"[^>]*>\s*([^<]+)', webpage, 'uploader', default=None),
            'formats': formats,
            'webpage_url': url,
        }


# ---------------------------------------------------------------- yt-dlp
def js_runtime():
    deno = os.environ.get('SEALOADER_DENO') or shutil.which('deno')
    if deno:
        return {'deno': {'path': deno}}
    node = shutil.which('node') or (sorted(glob.glob(os.path.expanduser('~/.nvm/versions/node/*/bin/node'))) or [None])[-1]
    if node:
        return {'node': {'path': node}}
    return None


def ffmpeg_dir():
    return os.environ.get('SEALOADER_FFMPEG') or (os.path.dirname(shutil.which('ffmpeg')) if shutil.which('ffmpeg') else None)


def base_opts(cookies_browser=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {'User-Agent': UA},
        'remote_components': ['ejs:github'],
    }
    rt = js_runtime()
    if rt:
        opts['js_runtimes'] = rt
    if ffmpeg_dir():
        opts['ffmpeg_location'] = ffmpeg_dir()
    if cookies_browser in ('chrome', 'chromium', 'brave', 'firefox', 'edge', 'opera', 'vivaldi', 'safari'):
        opts['cookiesfrombrowser'] = (cookies_browser,)
    return opts


def make_ydl(opts):
    ydl = yt_dlp.YoutubeDL(opts, auto_init=False)
    ydl.add_info_extractor(TokyVideoIE())
    ydl.add_default_info_extractors()
    return ydl


def clean_error(e):
    msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
    msg = re.sub(r'^ERROR:\s*', '', msg)
    low = msg.lower()
    if 'login' in low or 'cookies' in low or 'sign in' in low or 'private' in low:
        msg += '\n\nDica: ative "Cookies do navegador" nas configurações (ícone no canto) usando um navegador em que você esteja logado.'
    return msg


def summarize(info):
    formats = info.get('formats') or [info]
    heights = {}
    best_audio = 0
    for f in formats:
        size = f.get('filesize') or f.get('filesize_approx') or 0
        if f.get('vcodec', 'none') == 'none' and f.get('acodec', 'none') != 'none':
            best_audio = max(best_audio, size)
    for f in formats:
        h = f.get('height')
        if f.get('vcodec') == 'none' or (not h and f.get('acodec') not in (None, 'none') and not f.get('vcodec')):
            continue
        if not h:
            h = 0
        size = f.get('filesize') or f.get('filesize_approx') or 0
        if f.get('acodec') == 'none':
            size = size + best_audio if size else 0
        cur = heights.get(h)
        if not cur or size > cur['size']:
            heights[h] = {'height': h, 'short': min(h, f.get('width') or h), 'size': size, 'fps': f.get('fps')}
    if not heights and formats:
        heights[0] = {'height': 0, 'short': 0, 'size': 0, 'fps': None}
    return {
        'id': info.get('id'),
        'title': info.get('title') or info.get('id'),
        'uploader': info.get('uploader') or info.get('channel') or info.get('uploader_id'),
        'duration': info.get('duration'),
        'thumbnail': info.get('thumbnail'),
        'extractor': (info.get('extractor_key') or info.get('extractor') or '').lower(),
        'webpage_url': info.get('webpage_url'),
        'heights': sorted(heights.values(), key=lambda x: -x['height']),
        'raw': [{
            'id': f.get('format_id'), 'ext': f.get('ext'), 'res': f.get('resolution') or ('áudio' if f.get('vcodec') == 'none' else ''),
            'note': f.get('format_note') or '', 'vcodec': f.get('vcodec'), 'acodec': f.get('acodec'),
            'size': f.get('filesize') or f.get('filesize_approx'), 'tbr': f.get('tbr'),
        } for f in formats if f.get('format_id') and not (f.get('format_id') or '').startswith('sb')],
    }


def first_entry(info):
    if not info:
        raise yt_dlp.utils.DownloadError('Nenhum vídeo encontrado neste link')
    while info and info.get('_type') == 'playlist':
        entries = [e for e in (info.get('entries') or []) if e]
        if not entries:
            raise yt_dlp.utils.DownloadError('Nenhum vídeo encontrado neste link')
        info = entries[0]
    return info


@app.post('/api/info')
def api_info():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not re.match(r'^https?://', url):
        return jsonify(error='Cole um link válido (começando com http:// ou https://)'), 400
    try:
        with make_ydl(base_opts(data.get('cookies'))) as ydl:
            info = first_entry(ydl.extract_info(url, download=False))
        return jsonify(summarize(info))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=clean_error(e)), 422


def build_format(data):
    kind = data.get('kind', 'video')
    opts = {}
    if kind == 'raw':
        opts['format'] = data['format_id']
        return opts
    if kind == 'audio':
        codec = data.get('audio', 'mp3')
        opts['format'] = 'bestaudio/best'
        pp = {'key': 'FFmpegExtractAudio', 'preferredcodec': codec}
        if codec == 'mp3':
            pp['preferredquality'] = str(data.get('bitrate', '320'))
        opts['postprocessors'] = [pp]
        if codec in ('mp3', 'm4a', 'opus', 'flac'):
            opts['postprocessors'] += [{'key': 'FFmpegMetadata'}]
        return opts
    h = int(data.get('height') or 0)
    container = data.get('container', 'mp4')
    lim = f'[height<={h}]' if h else ''
    if container == 'mp4':
        opts['format'] = (f'bv*{lim}[vcodec^=avc1]+ba[ext=m4a]/bv*{lim}[ext=mp4]+ba[ext=m4a]/'
                          f'bv*{lim}+ba/b{lim}/bv*+ba/b')
        opts['merge_output_format'] = 'mp4'
        opts['postprocessors'] = [{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}]
    elif container == 'webm':
        opts['format'] = f'bv*{lim}[ext=webm]+ba[ext=webm]/bv*{lim}+ba/b{lim}/b'
        opts['merge_output_format'] = 'webm'
    else:
        opts['format'] = f'bv*{lim}+ba/b{lim}/b'
        opts['merge_output_format'] = 'mkv'
    return opts


def run_job(job_id, data):
    job = JOBS[job_id]
    outdir = os.path.join(WORK, job_id)
    os.makedirs(outdir, exist_ok=True)

    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done = d.get('downloaded_bytes') or 0
            frag = (d.get('fragment_index'), d.get('fragment_count'))
            pct = done / total * 100 if total else (frag[0] / frag[1] * 100 if all(frag) else 0)
            name = os.path.basename(d.get('filename') or '')
            part = 'áudio' if re.search(r'\.f\d+\.(m4a|webm|opus|mp3)', name) and job['parts'] > 1 else 'vídeo'
            job.update(stage='download', percent=round(pct, 1), speed=d.get('speed'), eta=d.get('eta'),
                       downloaded=done, total=total, part=part)
        elif d['status'] == 'finished':
            job['parts'] += 1

    def pp_hook(d):
        if d['status'] == 'started':
            names = {'Merger': 'Juntando vídeo e áudio', 'ExtractAudio': 'Convertendo áudio',
                     'VideoRemuxer': 'Ajustando contêiner', 'Metadata': 'Gravando metadados'}
            job.update(stage='process', label=names.get(d.get('postprocessor'), 'Processando'))

    opts = base_opts(data.get('cookies'))
    opts.update(build_format(data))
    opts.update({
        'outtmpl': os.path.join(outdir, '%(title).120B [%(id)s].%(ext)s'),
        'progress_hooks': [hook],
        'postprocessor_hooks': [pp_hook],
        'concurrent_fragment_downloads': 4,
        'windowsfilenames': True,
    })
    try:
        with make_ydl(opts) as ydl:
            ydl.download([data['url']])
        files = [f for f in glob.glob(os.path.join(outdir, '*')) if not f.endswith(('.part', '.ytdl'))]
        if not files:
            raise RuntimeError('O download terminou sem gerar arquivo')
        path = max(files, key=os.path.getsize)
        job.update(status='done', stage='done', percent=100, file=path,
                   filename=os.path.basename(path), size=os.path.getsize(path))
    except Exception as e:  # noqa: BLE001
        job.update(status='error', error=clean_error(e))


@app.post('/api/download')
def api_download():
    data = request.get_json(force=True)
    if not re.match(r'^https?://', data.get('url') or ''):
        return jsonify(error='Link inválido'), 400
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {'status': 'running', 'stage': 'start', 'percent': 0, 'parts': 0, 'created': time.time()}
    threading.Thread(target=run_job, args=(job_id, data), daemon=True).start()
    return jsonify(job=job_id)


@app.get('/api/job/<job_id>')
def api_job(job_id):
    job = JOBS.get(job_id) or abort(404)
    return jsonify({k: v for k, v in job.items() if k != 'file'})


@app.get('/api/file/<job_id>')
def api_file(job_id):
    job = JOBS.get(job_id) or abort(404)
    if job.get('status') != 'done':
        abort(409)
    return send_file(job['file'], as_attachment=True, download_name=job['filename'])


def is_private_host(url):
    try:
        host = urllib.parse.urlsplit(url).hostname
        return any(not ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(host, None))
    except Exception:  # noqa: BLE001
        return True


@app.get('/api/thumb')
def api_thumb():
    url = request.args.get('u', '')
    if not re.match(r'^https?://', url) or is_private_host(url):
        abort(400)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': urllib.parse.urljoin(url, '/')})
        with urllib.request.urlopen(req, timeout=15) as r:
            ctype = r.headers.get('Content-Type', 'image/jpeg')
            if not ctype.startswith('image/'):
                abort(415)
            body = r.read(15 * 1024 * 1024)
        return Response(body, mimetype=ctype, headers={'Cache-Control': 'max-age=86400'})
    except Exception:  # noqa: BLE001
        abort(502)


@app.get('/api/version')
def api_version():
    return jsonify(app='sealoader', ytdlp=yt_dlp.version.__version__, desktop=DESKTOP,
                   js=bool(js_runtime()), ffmpeg=bool(ffmpeg_dir()))


@app.get('/')
def index():
    return send_from_directory(WEB, 'index.html')


@app.get('/<path:name>')
def static_files(name):
    return send_from_directory(WEB, name)


# ---------------------------------------------------------------- background work
def janitor():
    while True:
        time.sleep(600)
        cutoff = time.time() - 3 * 3600
        for job_id, job in list(JOBS.items()):
            if job['created'] < cutoff:
                shutil.rmtree(os.path.join(WORK, job_id), ignore_errors=True)
                JOBS.pop(job_id, None)


def idle_exit():
    # desktop app: quit a few minutes after the last browser tab closed
    while True:
        time.sleep(30)
        busy = any(j['status'] == 'running' for j in JOBS.values())
        if not busy and time.time() - LAST_PING[0] > 240:
            os._exit(0)


def update_ytdlp():
    # sites change often; the new version is picked up on the next restart
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'yt-dlp[default,curl-cffi]'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def github(method, path, body=None):
    req = urllib.request.Request(f'https://api.github.com/repos/{CONFIG["github_repo"]}/{path}', method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={'Authorization': f'Bearer {CONFIG["github_token"]}',
                                          'Accept': 'application/vnd.github+json', 'User-Agent': 'sealoader'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def publish_backend():
    """Keep backend.json (branch `backend`) pointing at the current tunnel, so the fixed
    GitHub Pages site always finds this PC even though the trycloudflare URL changes."""
    import base64
    last = None
    while True:
        url = tunnel_url()
        if url and url != last:
            try:
                try:
                    cur = github('GET', 'contents/backend.json?ref=backend')
                    sha = cur['sha']
                    if json.loads(base64.b64decode(cur['content'])).get('url') == url:
                        last = url
                        continue
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                    sha = None
                content = json.dumps({'url': url, 'updated': int(time.time())}, indent=2).encode()
                body = {'message': f'backend: {url}', 'branch': 'backend', 'content': base64.b64encode(content).decode()}
                if sha:
                    body['sha'] = sha
                github('PUT', 'contents/backend.json', body)
                last = url
                print(f'[sealoader] backend publicado: {url}', flush=True)
            except Exception as e:  # noqa: BLE001
                print(f'[sealoader] falha ao publicar backend: {e}', flush=True)
        time.sleep(20)


def serve(port=PORT):
    threading.Thread(target=janitor, daemon=True).start()
    if DESKTOP:
        threading.Thread(target=idle_exit, daemon=True).start()
    else:
        if not getattr(sys, 'frozen', False):
            threading.Thread(target=update_ytdlp, daemon=True).start()
        if CONFIG.get('github_token') and CONFIG.get('github_repo') and CONFIG.get('publish_backend'):
            threading.Thread(target=publish_backend, daemon=True).start()
    app.run(host='127.0.0.1', port=port, threaded=True)


if __name__ == '__main__':
    serve()
