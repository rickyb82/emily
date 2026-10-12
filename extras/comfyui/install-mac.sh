#!/usr/bin/env bash
# ComfyUI nativo su macOS (Apple Silicon, Metal) con Flux quantizzato GGUF: adatto a 16-24 GB di memoria unificata.
#   ./install-mac.sh                 installa in ~/ComfyUI e scarica Flux.1 schnell Q8 (Apache 2.0, nessun token)
#   ./install-mac.sh --dev           anche Flux.1 dev Q6 (serve HF_TOKEN dopo aver accettato la licenza su Hugging Face)
#   ./install-mac.sh --sdxl          anche SDXL base (piu' leggero e veloce)
# Avvio: ~/ComfyUI/start.sh   → API su http://localhost:8188 (da FamilAI in Docker: http://host.docker.internal:8188)
set -euo pipefail
DIR="$HOME/ComfyUI"
DEV=0; SDXL=0
for a in "$@"; do case "$a" in --dev) DEV=1;; --sdxl) SDXL=1;; esac; done
say() { printf '\n\033[1;34m>> %s\033[0m\n' "$*"; }

command -v brew >/dev/null || { echo "!! Serve Homebrew (https://brew.sh)"; exit 1; }
brew list python@3.12 >/dev/null 2>&1 || { say "Installo Python 3.12"; brew install python@3.12; }
command -v git >/dev/null || brew install git

if [ ! -d "$DIR/.git" ]; then
  say "Clono ComfyUI in $DIR"; git clone https://github.com/comfyanonymous/ComfyUI.git "$DIR"
else
  say "Aggiorno ComfyUI"; git -C "$DIR" pull --ff-only || true
fi
cd "$DIR"
[ -d .venv ] || python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
say "Installo PyTorch (Metal) e dipendenze"
pip install -q --upgrade pip
pip install -q torch torchvision torchaudio
pip install -q -r requirements.txt
# nodo GGUF (modelli quantizzati: Flux ci sta in 24 GB)
if [ ! -d custom_nodes/ComfyUI-GGUF ]; then
  say "Installo il nodo ComfyUI-GGUF"; git clone https://github.com/city96/ComfyUI-GGUF.git custom_nodes/ComfyUI-GGUF
fi
pip install -q -r custom_nodes/ComfyUI-GGUF/requirements.txt

M="$DIR/models"; mkdir -p "$M"/{unet,clip,vae,checkpoints}
AUTH=(); [ -n "${HF_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $HF_TOKEN")
dl() { local url="$1" dest="$2"; if [ -s "$dest" ]; then echo "   gia' presente: $(basename "$dest")"; return; fi
      echo ">> $(basename "$dest")"; curl -L --fail --retry 3 --progress-bar "${AUTH[@]}" -o "$dest.part" "$url" && mv "$dest.part" "$dest"; }

say "Scarico encoder e VAE di Flux"
dl "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" "$M/clip/clip_l.safetensors"
dl "https://huggingface.co/city96/t5-v1_1-xxl-encoder-gguf/resolve/main/t5-v1_1-xxl-encoder-Q8_0.gguf" "$M/clip/t5-v1_1-xxl-encoder-Q8_0.gguf"
dl "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors" "$M/vae/ae.safetensors"
say "Scarico Flux.1 schnell Q8 (GGUF, ~12 GB)"
dl "https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q8_0.gguf" "$M/unet/flux1-schnell-Q8_0.gguf"
if [ "$DEV" = 1 ]; then
  say "Scarico Flux.1 dev Q6_K (GGUF, ~9 GB)"
  dl "https://huggingface.co/city96/FLUX.1-dev-gguf/resolve/main/flux1-dev-Q6_K.gguf" "$M/unet/flux1-dev-Q6_K.gguf"
fi
if [ "$SDXL" = 1 ]; then
  say "Scarico SDXL base"
  dl "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" "$M/checkpoints/sd_xl_base_1.0.safetensors"
  dl "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl_vae.safetensors" "$M/vae/sdxl_vae.safetensors"
fi

cat > "$DIR/start.sh" <<'EOS'
#!/usr/bin/env bash
cd "$(dirname "$0")" && source .venv/bin/activate
export PYTORCH_ENABLE_MPS_FALLBACK=1
exec python main.py --listen 0.0.0.0 --port 8188 --force-fp16 --preview-method auto
EOS
chmod +x "$DIR/start.sh"
say "Fatto. Avvia con:  $DIR/start.sh   (lascialo aperto in una finestra del Terminale)"
echo "   In FamilAI → Provider AI → Immagini in casa: indirizzo http://host.docker.internal:8188, modello flux-schnell-gguf$([ "$DEV" = 1 ] && echo ' (o flux-dev-gguf)')"
