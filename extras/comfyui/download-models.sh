#!/usr/bin/env bash
# Scarica i modelli open source per ComfyUI nelle cartelle giuste (volume ./storage/ComfyUI/models).
#   ./download-models.sh flux-schnell        Flux.1 [schnell] — Apache 2.0, 4 passi, nessun token richiesto
#   ./download-models.sh flux-dev            Flux.1 [dev] — qualita' massima, licenza non commerciale, serve HF_TOKEN
#   ./download-models.sh sdxl                Stable Diffusion XL base + refiner + VAE fp16
#   ./download-models.sh sd35                Stable Diffusion 3.5 Large (serve HF_TOKEN e accettazione licenza su HF)
# Token Hugging Face (per i modelli "gated"):  export HF_TOKEN=hf_xxx   (huggingface.co/settings/tokens)
set -euo pipefail
cd "$(dirname "$0")"
M="storage/ComfyUI/models"
mkdir -p "$M"/{checkpoints,unet,diffusion_models,clip,text_encoders,vae,loras}
AUTH=(); [ -n "${HF_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $HF_TOKEN")

dl() {  # dl <url> <destinazione>
  local url="$1" dest="$2"
  if [ -s "$dest" ]; then echo "   gia' presente: $(basename "$dest")"; return; fi
  echo ">> $(basename "$dest")"
  curl -L --fail --retry 3 --progress-bar ${AUTH[@]+"${AUTH[@]}"} -o "$dest.part" "$url" && mv "$dest.part" "$dest"
}

common_flux() {
  dl "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" "$M/clip/clip_l.safetensors"
  dl "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" "$M/clip/t5xxl_fp16.safetensors"
  dl "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors" "$M/vae/ae.safetensors"
}

for what in "$@"; do
  case "$what" in
    flux-schnell)
      common_flux
      dl "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors" "$M/unet/flux1-schnell.safetensors";;
    flux-dev)
      [ -n "${HF_TOKEN:-}" ] || { echo "!! Flux.1 dev e' 'gated': accetta la licenza su huggingface.co/black-forest-labs/FLUX.1-dev e imposta HF_TOKEN"; exit 1; }
      common_flux
      dl "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors" "$M/unet/flux1-dev.safetensors";;
    sdxl)
      dl "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" "$M/checkpoints/sd_xl_base_1.0.safetensors"
      dl "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl_vae.safetensors" "$M/vae/sdxl_vae.safetensors";;
    sd35)
      [ -n "${HF_TOKEN:-}" ] || { echo "!! SD 3.5 e' 'gated': accetta la licenza su huggingface.co/stabilityai/stable-diffusion-3.5-large e imposta HF_TOKEN"; exit 1; }
      dl "https://huggingface.co/stabilityai/stable-diffusion-3.5-large/resolve/main/sd3.5_large.safetensors" "$M/checkpoints/sd3.5_large.safetensors"
      dl "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" "$M/clip/clip_l.safetensors"
      dl "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" "$M/clip/t5xxl_fp16.safetensors"
      dl "https://huggingface.co/stabilityai/stable-diffusion-3.5-large/resolve/main/text_encoders/clip_g.safetensors" "$M/clip/clip_g.safetensors";;
    *) echo "sconosciuto: $what (usa flux-schnell | flux-dev | sdxl | sd35)"; exit 1;;
  esac
done
echo ">> Fatto. Riavvia ComfyUI se era gia' avviato: docker compose restart comfyui"
