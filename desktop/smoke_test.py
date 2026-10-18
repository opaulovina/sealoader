"""Teste do app de desktop já empacotado (roda no GitHub Actions depois do build).

Abre o executável gerado, cria um vídeo de teste com o ffmpeg embutido, serve ele localmente e
pede ao Sealoader para baixar como MP4 e como MP3. Assim testa yt-dlp + ffmpeg + empacotamento
sem depender do YouTube (que costuma bloquear os servidores do GitHub). O YouTube é tentado
também, mas só como informação.

    python desktop/smoke_test.py
"""
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'build', 'pyi-dist')
EXE = {'win32': os.path.join(DIST, 'Sealoader', 'Sealoader.exe'),
       'darwin': os.path.join(DIST, 'Sealoader.app', 'Contents', 'MacOS', 'Sealoader')}.get(
    sys.platform, os.path.join(DIST, 'Sealoader', 'Sealoader'))
TOOLS = os.path.join(ROOT, 'build', 'tools')
PORT = 8799
API = f'http://127.0.0.1:{PORT}'


def call(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def download(url, **opts):
    job = call('/api/download', {'url': url, **opts})['job']
    for _ in range(240):
        st = call(f'/api/job/{job}')
        if st['status'] != 'running':
            return st
        time.sleep(1)
    raise TimeoutError(url)


def main():
    media = os.path.join(ROOT, 'build', 'smoke')
    os.makedirs(media, exist_ok=True)
    ffmpeg = os.path.join(TOOLS, 'ffmpeg' + ('.exe' if os.name == 'nt' else ''))
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', os.path.join(media, 'teste.mp4')], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=media)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    video_url = f'http://127.0.0.1:{srv.server_address[1]}/teste.mp4'

    app = subprocess.Popen([EXE, '--no-browser', '--port', str(PORT)])
    try:
        for _ in range(120):
            try:
                v = call('/api/version')
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        else:
            raise SystemExit('o app não abriu')
        print('versão:', v, flush=True)
        assert v['desktop'] and v['ffmpeg'] and v['js'], v

        ok = True
        for name, opts in (('mp4', {'kind': 'video', 'height': 0, 'container': 'mp4'}),
                           ('mp3', {'kind': 'audio', 'audio': 'mp3', 'bitrate': '192'})):
            st = download(video_url, **opts)
            print(f'{name}:', st.get('filename') or st.get('error'), st.get('size'), flush=True)
            ok &= st['status'] == 'done' and st['filename'].endswith('.' + name) and st['size'] > 1000

        try:
            info = call('/api/info', {'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw'})
            print('youtube (informativo):', info.get('error') or info['title'], flush=True)
        except Exception as e:  # noqa: BLE001
            print('youtube (informativo):', e, flush=True)

        if not ok:
            raise SystemExit('falhou')
        print('✓ app funcionando', flush=True)
    finally:
        app.terminate()
        srv.shutdown()


if __name__ == '__main__':
    main()
