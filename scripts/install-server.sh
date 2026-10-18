#!/bin/bash
# Instala o Sealoader como SERVIDOR DA CASA neste Linux (systemd + túnel Cloudflare + publicação no GitHub).
# Uso:  ./scripts/install-server.sh        (rode de dentro do repositório clonado)
# Reaproveita o config.json se ele existir (copie do computador antigo para manter a mesma senha).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "→ Dependências do sistema (python3-venv, ffmpeg, curl)"
for p in python3 ffmpeg curl; do command -v $p >/dev/null || { echo "Falta '$p'. Rode: sudo apt install python3-venv ffmpeg curl"; exit 1; }; done
python3 -c "import venv" 2>/dev/null || { echo "Falta python3-venv. Rode: sudo apt install python3-venv"; exit 1; }

echo "→ Ambiente Python"
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/python -m pip install -q -U pip
venv/bin/python -m pip install -q -U -r requirements.txt

echo "→ Runtime JavaScript para o YouTube (deno)"
mkdir -p bin
if ! command -v deno >/dev/null && [ ! -x bin/deno ]; then
  curl -sfL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip
  python3 -c "import zipfile;zipfile.ZipFile('/tmp/deno.zip').extractall('bin')"; chmod +x bin/deno; rm /tmp/deno.zip
fi

echo "→ cloudflared"
[ -x bin/cloudflared ] || { curl -sfL -o bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64; chmod +x bin/cloudflared; }

echo "→ Configuração (senha, GitHub)"
venv/bin/python - <<PY
import json, os, subprocess
p = 'config.json'
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg.setdefault('github_repo', 'opaulovina/sealoader')
cfg.setdefault('pages_url', 'https://opaulovina.github.io/sealoader/')
if not cfg.get('github_token'):
    try:
        cfg['github_token'] = subprocess.check_output(['gh', 'auth', 'token'], text=True).strip()
    except Exception:
        print('  ! Sem token do GitHub. Rode "gh auth login" e depois este script de novo.')
json.dump(cfg, open(p, 'w'), indent=2); os.chmod(p, 0o600)
PY

echo "→ Serviços systemd (iniciam com o computador)"
mkdir -p ~/.config/systemd/user
sed "s#@ROOT@#$ROOT#g" scripts/systemd/sealoader.service > ~/.config/systemd/user/sealoader.service
sed "s#@ROOT@#$ROOT#g" scripts/systemd/sealoader-tunnel.service > ~/.config/systemd/user/sealoader-tunnel.service
systemctl --user daemon-reload
systemctl --user enable --now sealoader.service sealoader-tunnel.service
loginctl enable-linger "$USER" || echo "  ! Não deu para ativar o início sem login (loginctl enable-linger). Ele inicia quando você fizer login."

echo "→ Atalho no menu"
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$ROOT/scripts/sealoader" ~/.local/bin/sealoader
cp web/icon.svg ~/.local/share/icons/hicolor/scalable/apps/sealoader.svg
cat > ~/.local/share/applications/sealoader.desktop <<DESK
[Desktop Entry]
Type=Application
Name=Sealoader
GenericName=Baixar vídeos e QR Code
Comment=Baixe vídeos do YouTube, TikTok, Instagram, X, Telegram e TokyVideo e gere QR codes
Exec=$ROOT/scripts/sealoader
Icon=sealoader
Terminal=false
Categories=Network;AudioVideo;Utility;
Keywords=youtube;download;video;qr;tiktok;instagram;
DESK
update-desktop-database ~/.local/share/applications 2>/dev/null || true

echo
echo "✓ Pronto. Senha: $(venv/bin/python -c "import json;print(json.load(open('config.json'))['password'])")"
echo "  Site fixo: https://opaulovina.github.io/sealoader/"
