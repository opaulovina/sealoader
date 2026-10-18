# Sealoader

Baixa vídeos do **YouTube, TikTok, Instagram, X (Twitter), Telegram, TokyVideo** (e mais 1.800 sites suportados pelo [yt-dlp](https://github.com/yt-dlp/yt-dlp)) em vários formatos, e gera **QR codes estáticos** (que nunca expiram) com personalização: cores, degradê, formato dos pontos e imagem no centro.

O visual reproduz o estilo do arquivo [Google Sea Glass](https://www.figma.com/community/file/1691510784131240473/google-sea-glass) do Figma (Julian, CC BY 4.0): pílulas pastel grossas, com granulado leve, borda interna clara e sombra suave embaixo.

- **Site fixo:** https://opaulovina.github.io/sealoader/
- **Apps:** https://github.com/opaulovina/sealoader/releases/latest

> **Senha, token do GitHub e chave do Android NÃO ficam neste repositório** (que é público). Eles ficam em `config.json` e `android/keystore/`, só no computador servidor. Veja [Backup](#backup-o-que-não-pode-perder).

---

## Sumário
1. [Como tudo se encaixa](#como-tudo-se-encaixa)
2. [Quem usa o quê](#quem-usa-o-quê)
3. [Estrutura do repositório](#estrutura-do-repositório)
4. [Servidor da casa](#servidor-da-casa)
5. [Trocar de computador / Raspberry Pi](#trocar-de-computador--raspberry-pi)
6. [Backup: o que não pode perder](#backup-o-que-não-pode-perder)
7. [Publicar uma nova versão dos apps](#publicar-uma-nova-versão-dos-apps)
8. [Instalar em cada aparelho](#instalar-em-cada-aparelho)
9. [Desenvolvimento](#desenvolvimento)
10. [Como funciona por dentro](#como-funciona-por-dentro)
11. [Problemas comuns](#problemas-comuns)
12. [Alternativas para o link fixo (Tailscale, domínio)](#alternativas-para-o-link-fixo)

---

## Como tudo se encaixa

```
                    ┌──────────────────────────────────────────┐
                    │ GitHub Pages (grátis, link nunca muda)   │
 iPhone / Android ─▶│ opaulovina.github.io/sealoader           │──── QR code funciona aqui mesmo,
 navegador          │ (interface: web/index.html)              │     sem servidor nenhum
                    └───────────────┬──────────────────────────┘
                                    │ 1. lê backend.json (branch "backend") para saber
                                    │    o endereço atual do servidor
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │ Túnel Cloudflare (trycloudflare.com)     │ ← o endereço muda quando reinicia,
                    └───────────────┬──────────────────────────┘   mas o servidor republica
                                    │ 2. pedidos com senha (token)  sozinho em backend.json
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │ Servidor da casa (seu Linux / Raspberry) │
                    │ server.py + yt-dlp + ffmpeg + deno        │
                    └──────────────────────────────────────────┘

 Windows / Mac / Linux ─▶ app instalado: o MESMO server.py roda dentro do app, no próprio
                          computador. Não precisa de servidor, internet da casa nem senha.
```

- **iPhone:** o Safari não deixa rodar um baixador local, então baixar vídeo sempre passa pelo servidor. O QR code funciona sempre.
- **Android:** o APK leva a interface embutida e usa o servidor para baixar. Ele também aparece em **Compartilhar** no YouTube, Instagram, TikTok etc.: é só tocar em Compartilhar → Sealoader.
- **Windows / Mac / Linux:** app 100% independente, com yt-dlp, ffmpeg e deno embutidos. O yt-dlp se atualiza sozinho uma vez por dia (fica em `yt-dlp.zip` na pasta de dados do app).

## Quem usa o quê

| Pessoa / aparelho | Como usa | Precisa do servidor ligado? |
|---|---|---|
| Paulo (Linux) | menu → Sealoader (servidor da casa) ou o AppImage | não (é o próprio servidor) |
| Namorada (Mac) | app `.dmg` | **não** |
| Mãe (Windows) | instalador `.exe` | **não** |
| Android | APK, ou o site | sim, para baixar vídeo |
| iPhone | site no Safari → "Adicionar à Tela de Início" | sim, para baixar vídeo |

## Estrutura do repositório

```
server.py                 backend (Flask + yt-dlp); serve a interface e a API
web/                      interface (um único index.html) + ícones, manifest, service worker
  index.html              tudo: CSS Sea Glass, downloader, QR code, login, ponte Android
  qr-code-styling.js      biblioteca de QR (MIT), copiada para funcionar offline
desktop/
  app.py                  ponto de entrada dos apps de desktop (sobe o server.py local, abre o navegador)
  build.py                gera o app do sistema atual (AppImage / instalador .exe / .dmg)
  installer.iss           instalador do Windows (Inno Setup)
  smoke_test.py           testa o app empacotado (baixa um vídeo de teste em MP4 e MP3)
android/                  app Android (Java, sem dependências externas)
  app/src/main/java/.../MainActivity.java   WebView + downloads + ponte window.SealoaderAndroid
scripts/
  install-server.sh       instala/reinstala o servidor da casa num Linux (x86_64 ou Raspberry Pi)
  sealoader               atalho do menu: garante que o serviço está rodando e abre o navegador
  systemd/                serviços sealoader (servidor) e sealoader-tunnel (Cloudflare)
.github/workflows/
  pages.yml               publica web/ no GitHub Pages a cada push em main
  release.yml             gera e publica os apps ao enviar uma tag v*
```

Arquivos **locais** (no `.gitignore`, nunca vão para o GitHub): `config.json`, `android/keystore/`, `venv/`, `bin/`, `build/`, `dist/`.

## Servidor da casa

Instalado em `~/sealoader`, roda como serviço do usuário (systemd) e **inicia sozinho com o computador**, mesmo sem login (`loginctl enable-linger`).

```bash
systemctl --user status sealoader sealoader-tunnel     # está rodando?
systemctl --user restart sealoader                     # reiniciar depois de mexer no código
journalctl --user -u sealoader -f                      # ver o log ao vivo
journalctl --user -u sealoader-tunnel -n 50            # log do túnel
```

**Senha e link para compartilhar:** abra o Sealoader neste PC e clique no ícone de ajustes (canto superior direito) → "Compartilhar". Lá aparecem o link fixo, a senha, um QR code e o botão "Copiar convite". A senha fica em `config.json` → `"password"`.

**Trocar a senha:** edite `"password"` em `config.json` e rode `systemctl --user restart sealoader`. Todo mundo vai precisar digitar a senha nova (os logins antigos deixam de valer).

### `config.json`
```jsonc
{
  "password": "…",            // senha que as pessoas digitam
  "secret": "…",              // assina os logins (tokens); trocar = desloga todo mundo
  "github_repo": "opaulovina/sealoader",
  "pages_url": "https://opaulovina.github.io/sealoader/",  // também libera o CORS do site
  "github_token": "gho_…",    // usado para atualizar backend.json; vem de `gh auth token`
  "publish_backend": true      // false = não publica o endereço do túnel no GitHub
}
```

## Trocar de computador / Raspberry Pi

1. No computador **novo** (Ubuntu/Zorin/Debian, x86_64 ou Raspberry Pi OS 64 bits):
   ```bash
   sudo apt install git python3-venv ffmpeg curl gh
   gh auth login                       # entra na conta opaulovina
   git clone https://github.com/opaulovina/sealoader ~/sealoader
   ```
2. Copie do computador **antigo** o `~/sealoader/config.json`, para manter a mesma senha (senão é gerada uma nova). Se for gerar apps Android neste computador, copie também a pasta `~/sealoader/android/keystore/`.
3. Instale:
   ```bash
   cd ~/sealoader && ./scripts/install-server.sh
   ```
   O script cria o ambiente Python, baixa deno e cloudflared, configura o token do GitHub, instala e liga os serviços e cria o atalho no menu.
4. **Desligue o servidor antigo** (`systemctl --user disable --now sealoader sealoader-tunnel`), senão os dois ficam disputando o `backend.json`.

Em 1 minuto, o site fixo já encontra o servidor novo, sem precisar mandar link nenhum para ninguém.

## Backup: o que não pode perder

| Arquivo | Para quê | Se perder… |
|---|---|---|
| `config.json` | senha + segredo dos logins | gera uma senha nova; todo mundo digita de novo |
| `android/keystore/release.jks` + `keystore.properties` | assinatura do APK | atualizações do APK não instalam por cima; é preciso desinstalar e instalar de novo. Uma cópia fica nos *secrets* do GitHub (`SEALOADER_KEYSTORE_B64`), mas eles não podem ser lidos de volta. |

Guarde os dois num lugar seguro (pendrive, gerenciador de senhas, Google Drive privado).

## Publicar uma nova versão dos apps

```bash
cd ~/sealoader
git add -A && git commit -m "o que mudou"
git push                       # atualiza o site (GitHub Pages) em ~1 minuto
git tag v1.0.1 && git push origin v1.0.1    # gera os apps e publica a release (~15 min)
```

O workflow `release.yml` compila em máquinas Windows, Mac (Apple Silicon e Intel) e Linux do GitHub, **testa cada app** (`desktop/smoke_test.py`) e publica:

- `Sealoader-Windows-Setup.exe`
- `Sealoader-Mac-AppleSilicon.dmg` e `Sealoader-Mac-Intel.dmg`
- `Sealoader-Linux-x86_64.AppImage`
- `Sealoader-Android.apk`

Os botões no rodapé do site usam `releases/latest/download/…`, então sempre baixam a versão mais nova. Acompanhe o build com `gh run watch` ou na aba **Actions** do repositório.

**Gerar localmente** (só o app do sistema atual):
```bash
python3 -m venv build/venv && build/venv/bin/pip install -r requirements.txt pyinstaller pillow
build/venv/bin/python desktop/build.py             # → dist/
cd android && ./gradlew assembleRelease            # → android/app/build/outputs/apk/release/
```

## Instalar em cada aparelho

O app não é assinado por Apple ou Microsoft (isso custa US$99/ano na Apple e mais ainda na Microsoft), então na primeira vez o sistema pergunta se você confia:

- **Windows:** baixe `Sealoader-Windows-Setup.exe`. Se aparecer "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**. O app aparece no Menu Iniciar e na Área de Trabalho.
- **Mac:** baixe o `.dmg` certo (**Apple Silicon** para Macs M1/M2/M3/M4, de 2020 em diante; **Intel** para os mais antigos; veja em  → Sobre Este Mac). Arraste o Sealoader para Aplicativos. Na primeira vez que abrir, se o Mac bloquear: **Ajustes do Sistema → Privacidade e Segurança → role até o fim → "Abrir Mesmo Assim"**. Depois disso abre normal.
- **Linux:** baixe o `.AppImage`, dê permissão (`chmod +x Sealoader-Linux-x86_64.AppImage`, ou botão direito → Propriedades → "Permitir executar") e abra.
- **Android:** baixe `Sealoader-Android.apk` no celular e abra. O Android pede para **permitir instalar de fontes desconhecidas** para o navegador. Depois, em qualquer app, toque em **Compartilhar → Sealoader**.
- **iPhone:** abra o site no **Safari** → botão Compartilhar → **Adicionar à Tela de Início**.

Os apps de desktop abrem no navegador padrão e fecham sozinhos uns 4 minutos depois que a aba é fechada (se não houver download em andamento). Os arquivos baixados vão para a pasta Downloads do navegador. No Android vão para `Downloads/Sealoader`, e os QR codes vão para a galeria (`Imagens/Sealoader`).

## Desenvolvimento

```bash
cd ~/sealoader
systemctl --user stop sealoader             # libera a porta 8765
venv/bin/python server.py                   # http://127.0.0.1:8765
# … mexe em web/index.html (recarregue a página) ou server.py (reinicie) …
systemctl --user start sealoader
```

- **Interface:** tudo em `web/index.html`. As cores ficam nos tokens `--pink-*`, `--blue-*`, `--coral-*`, `--mint-*`, `--sun-*` e `--frost-*`. O material de vidro é a classe `.glass` (granulado em `.glass::after`, intensidade no `opacity`). A variante `.flat` tem sombra menor.
- **Novos sites:** quase sempre o yt-dlp já suporta. Para um site que ele não conhece, siga o exemplo de `TokyVideoIE` em `server.py` e registre-o em `make_ydl()`.
- **Formatos de download:** veja `build_format()` em `server.py`.
- **Android:** o APK embute a pasta `web/` (veja `assets.srcDirs` em `android/app/build.gradle`). Mudou a interface? Gere um APK novo, ou use o site, que atualiza sozinho.

## Como funciona por dentro

**Três modos, um código só (`server.py`):**
- *Servidor da casa*: atende pedidos locais sem senha e pedidos pelo túnel (que trazem cabeçalhos `Cf-*`) só com token. Libera CORS apenas para a origem do `pages_url`.
- *App de desktop* (`SEALOADER_DESKTOP=1`): tudo local, sem senha. Usa o ffmpeg e o deno embutidos (`SEALOADER_FFMPEG` / `SEALOADER_DENO`) e fecha quando ocioso (a página manda `/api/ping` a cada 30 s).
- *Desenvolvimento*: igual ao servidor, rodando à mão.

**Link fixo sem pagar nada:** o túnel gratuito da Cloudflare ganha um endereço novo a cada reinício. A cada 20 s, `publish_backend()` confere o endereço atual (`http://127.0.0.1:20241/quicktunnel`) e, se mudou, grava `backend.json` na branch `backend` do repositório pela API do GitHub. O site (`connect()` em `index.html`) lê esse arquivo pela API do GitHub (com o `raw.githubusercontent.com` como reserva) e guarda o endereço por 10 minutos.

**Login:** `POST /api/login` com a senha devolve um token assinado (`itsdangerous`, válido por 1 ano, invalidado se a senha mudar). O site guarda o token no `localStorage` e manda no cabeçalho `Authorization` (ou `?t=` nos links de arquivo). Foi feito com token em vez de cookie porque o Safari bloqueia cookies entre domínios diferentes (github.io ↔ trycloudflare.com). Após 5 erros de senha, aquele IP fica bloqueado por 5 minutos.

**Downloads:** `POST /api/info` lê os formatos; `POST /api/download` cria um job numa thread; `GET /api/job/<id>` dá o progresso; `GET /api/file/<id>` entrega o arquivo. Os arquivos ficam na pasta temporária `sealoader-jobs` e são apagados depois de 3 horas.

**YouTube:** exige um runtime JavaScript para resolver os desafios do site. O servidor usa o deno (`bin/deno`), com o node como reserva, e os apps de desktop levam o deno embutido. O pacote `yt-dlp-ejs` traz os scripts dos desafios, e `remote_components: ejs:github` busca versões novas se precisar.

**Atualização do yt-dlp:**
- *Servidor:* `pip install -U` toda vez que o serviço inicia; vale no próximo reinício.
- *Apps de desktop:* baixam o `yt-dlp` oficial (um zip) uma vez por dia na pasta de dados (`%LOCALAPPDATA%\Sealoader`, `~/Library/Application Support/Sealoader` ou `~/.local/share/Sealoader`) e importam dele (`_UpdatedYtDlp` em `desktop/app.py`). Se a versão nova der erro, voltam para a embutida.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "O servidor está desligado" no site/celular | Ligue o PC servidor. Confira com `systemctl --user status sealoader sealoader-tunnel`. Se o túnel estiver em loop de erro, veja `journalctl --user -u sealoader-tunnel -n 50`. |
| O site não acha o servidor mesmo ligado | `journalctl --user -u sealoader \| grep backend` deve mostrar "backend publicado". Se mostrar falha 401, o token do GitHub expirou: `gh auth login` e depois apague `github_token` do `config.json` e rode `./scripts/install-server.sh`. |
| YouTube: "Sign in to confirm you're not a bot" | Ative **Cookies do navegador** (ícone de ajustes) com um navegador logado no YouTube. |
| Instagram / X pedem login | Mesma coisa: cookies do navegador. |
| TikTok: "Your IP address is blocked" | É o TikTok bloqueando aquele vídeo para o IP/país. Não há o que fazer pelo app. |
| TokyVideo: "bloqueou este vídeo no seu país" | Bloqueio regional do próprio site. |
| Um site parou de funcionar de repente | Normalmente o yt-dlp já corrigiu: reinicie o serviço (ele se atualiza) ou feche e abra o app de desktop duas vezes. |
| Mac: "Sealoader está danificado e não pode ser aberto" | No Terminal: `xattr -dr com.apple.quarantine /Applications/Sealoader.app` |

## Alternativas para o link fixo

O esquema atual (GitHub Pages + `backend.json`) já dá um link que nunca muda, de graça. Outras opções, se um dia quiser:

- **Tailscale Funnel** (grátis): instala o Tailscale no servidor (`curl -fsSL https://tailscale.com/install.sh | sh`, depois `sudo tailscale up`), ativa o Funnel no painel e roda `tailscale funnel --bg 8765`. O servidor ganha um endereço fixo do tipo `https://nome-do-pc.tailXXXX.ts.net`, e o túnel da Cloudflare deixa de ser necessário. Para usar: `systemctl --user disable --now sealoader-tunnel`, coloque `"publish_backend": false` no `config.json` e grave esse endereço uma única vez em `backend.json` na branch `backend` (`{"url": "https://nome-do-pc.tailXXXX.ts.net"}`).
- **Domínio próprio** (~R$40/ano, ex.: `sealoader.com.br`) + túnel nomeado da Cloudflare (`cloudflared tunnel login`, `cloudflared tunnel create sealoader`, `cloudflared tunnel route dns sealoader app.sealoader.com.br`). Também é um endereço fixo para o servidor.

Nos dois casos o site do GitHub Pages continua funcionando igual, porque só muda o endereço gravado em `backend.json`.

---

Créditos: visual inspirado em [Google Sea Glass](https://www.figma.com/community/file/1691510784131240473/google-sea-glass) de Julian (CC BY 4.0) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) · [qr-code-styling](https://github.com/kozakdenys/qr-code-styling) (MIT) · [FFmpeg](https://ffmpeg.org) (GPL) · [Deno](https://deno.com) (MIT) · [cloudflared](https://github.com/cloudflare/cloudflared) (Apache 2.0).
