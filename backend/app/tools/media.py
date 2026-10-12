"""Generazione immagini (OpenAI gpt-image) e video (Gemini / Veo)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import base64
import logging
import uuid

from ..config import get_settings
from ..models import FileAsset
from .registry import ToolContext, ToolResult, register

settings = get_settings()
log = logging.getLogger(__name__)

CHILD_PROMPT_PREFIX = ("Illustrazione adatta ai bambini, allegra, colorata, senza violenza né contenuti spaventosi "
                       "o inadatti ai minori. ")


async def _save_generated(ctx: ToolContext, data: bytes, ext: str, mime: str, label: str) -> FileAsset:
    fid = uuid.uuid4().hex
    path = settings.generated_dir / f"{fid}.{ext}"
    path.write_bytes(data)
    asset = FileAsset(id=fid, family_id=ctx.user.family_id, owner_id=ctx.user.id, project_id=ctx.project_id,
                      conversation_id=ctx.conversation_id, filename=f"{label}.{ext}", mime=mime, size=len(data),
                      path=str(path), kind="generated")
    ctx.db.add(asset)
    await ctx.db.commit()
    return asset


@register(
    "generate_image",
    "Genera un'immagine a partire da una descrizione testuale. Descrivi soggetto, stile e dettagli (in inglese rende meglio "
    "con i modelli locali).",
    {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "Descrizione dell'immagine"},
        "size": {"type": "string", "enum": ["1024x1024", "1024x1536", "1536x1024"], "description": "Dimensione"},
        "negative": {"type": "string", "description": "Cosa evitare (solo modelli locali SDXL/SD3.5)"},
        "provider": {"type": "string", "enum": ["auto", "comfyui", "openai", "gemini"],
                     "description": "Chi genera: auto (impostazione del server), comfyui (locale/Flux), openai (gpt-image: ottimo con il testo nelle immagini), gemini (Imagen). Usa quello che chiede l'utente."}},
     "required": ["prompt"]},
    usage_kind="image",
)
async def generate_image(args: dict, ctx: ToolContext) -> ToolResult:
    prompt = str(args.get("prompt", "")).strip()
    if ctx.policy.get("moderation"):
        prompt = CHILD_PROMPT_PREFIX + prompt
    size = args.get("size") or "1024x1024"

    # scelta del provider: richiesta esplicita nel tool > impostazione del server > auto (ComfyUI in casa, poi OpenAI, poi Gemini)
    pref = settings.image_provider
    want = str(args.get("provider") or "auto").lower()
    if want in ("comfyui", "openai", "gemini"):
        ok = {"comfyui": bool(settings.comfyui_url), "openai": bool(settings.openai_api_key), "gemini": bool(settings.gemini_api_key)}[want]
        if not ok:
            return ToolResult(f"Il provider immagini '{want}' non e' configurato su questo server (manca indirizzo/chiave): "
                              f"disponibili: {', '.join(k for k, v in {'comfyui': bool(settings.comfyui_url), 'openai': bool(settings.openai_api_key), 'gemini': bool(settings.gemini_api_key)}.items() if v) or 'nessuno'}.",
                              is_error=True)
        pref = want
    if pref == "comfyui" or (pref == "auto" and settings.comfyui_url):
        backend = "comfyui" if settings.comfyui_url else None
    elif pref == "openai" or (pref == "auto" and settings.openai_api_key):
        backend = "openai" if settings.openai_api_key else None
    elif pref == "gemini" or (pref == "auto" and settings.gemini_api_key):
        backend = "gemini" if settings.gemini_api_key else None
    else:
        backend = None
    if not backend:
        return ToolResult("Generazione immagini non disponibile: serve ComfyUI in casa, oppure una chiave OpenAI (gpt-image-1) o Gemini (Imagen). "
                          "Un amministratore puo' configurarli in Famiglia → Provider AI.", is_error=True)
    try:
        if backend == "comfyui":
            from ..services import comfyui

            data, model_used = await comfyui.generate(prompt, size, negative=str(args.get("negative") or ""))
            tool_usage = {"provider": "comfyui", "model": model_used, "detail": f"immagine {size}"}
        elif backend == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            r = await client.images.generate(model=settings.image_model, prompt=prompt, size=size, n=1)
            b64 = r.data[0].b64_json
            if not b64:
                return ToolResult("Il provider non ha restituito l'immagine", is_error=True)
            data = base64.b64decode(b64)
            model_used = settings.image_model
            ru = getattr(r, "usage", None)
            tool_usage = {"provider": "openai", "model": model_used, "input_tokens": int(getattr(ru, "input_tokens", 0) or 0),
                          "output_tokens": int(getattr(ru, "output_tokens", 0) or 0), "detail": f"immagine {size}"}
        else:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=settings.gemini_api_key)
            ratio = {"1024x1536": "3:4", "1536x1024": "4:3"}.get(size, "1:1")
            r = await client.aio.models.generate_images(
                model=settings.gemini_image_model, prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio=ratio,
                                                  person_generation="allow_adult"))
            if not r.generated_images:
                return ToolResult("Il provider non ha restituito l'immagine (prompt rifiutato dai filtri?)", is_error=True)
            data = r.generated_images[0].image.image_bytes
            model_used = settings.gemini_image_model
            tool_usage = {"provider": "gemini", "model": model_used, "detail": f"immagine {size}"}
        asset = await _save_generated(ctx, data, "png", "image/png", "immagine")
    except Exception as e:
        log.exception("Generazione immagine fallita")
        return ToolResult(f"Generazione immagine fallita ({backend}): {type(e).__name__}: {e}", is_error=True)
    url = f"/files/{asset.id}"
    return ToolResult(f"Immagine generata con {model_used} e mostrata all'utente (id {asset.id}). Descrivila brevemente.",
                      artifacts=[{"type": "image", "file_id": asset.id, "url": url, "mime": "image/png"}], usage=tool_usage)


_veo_cache: dict = {"model": "", "checked": False}


async def _resolve_veo_model(client) -> str:
    """Il modello Veo impostato, se esiste nell'account; altrimenti il piu' recente che supporta la generazione video.
    (Gli id cambiano spesso: veo-3.1-generate-preview, veo-3.0-generate-001, veo-3.0-fast-generate-001, veo-2.0-generate-001...)"""
    if _veo_cache["checked"] and _veo_cache["model"]:
        return _veo_cache["model"]
    want = settings.video_model
    try:
        names = []
        async for m in await client.aio.models.list():
            name = (m.name or "").replace("models/", "")
            actions = list(getattr(m, "supported_actions", None) or [])
            if "veo" in name and (not actions or "predictLongRunning" in actions):
                names.append(name)
        _veo_cache["checked"] = True
        if want in names or not names:
            _veo_cache["model"] = want
            return want
        # ordina: versione piu' alta prima, 'generate' prima di 'fast'
        def key(n: str):
            import re as _re
            v = _re.search(r"veo-(\d+)\.(\d+)", n)
            return (int(v.group(1)) if v else 0, int(v.group(2)) if v else 0, "fast" not in n, "preview" not in n)
        names.sort(key=key, reverse=True)
        log.warning("Modello video %s non disponibile: uso %s", want, names[0])
        _veo_cache["model"] = names[0]
        return names[0]
    except Exception as e:
        log.warning("Elenco modelli Veo non disponibile: %s", e)
        return want


@register(
    "generate_video",
    "Genera un breve video (circa 8 secondi) da una descrizione testuale. L'operazione può richiedere qualche minuto.",
    {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "Descrizione della scena"},
        "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"], "description": "Formato"},
        "image_file_id": {"type": "string", "description": "Opzionale: id di un'immagine (allegata o generata) da animare (immagine→video)"},
        "provider": {"type": "string", "enum": ["auto", "comfyui", "gemini"], "description": "Chi genera: auto, comfyui (Wan 2.2 in casa), gemini (Veo). Usa quello che chiede l'utente."}},
     "required": ["prompt"]},
    usage_kind="video",
)
async def generate_video(args: dict, ctx: ToolContext) -> ToolResult:
    if not settings.gemini_api_key:
        return ToolResult("Generazione video non configurata (manca GEMINI_API_KEY)", is_error=True)
    prompt = str(args.get("prompt", "")).strip()
    if ctx.policy.get("moderation"):
        prompt = CHILD_PROMPT_PREFIX + prompt
    pref = (settings.video_provider or "auto").lower()
    want = str(args.get("provider") or "auto").lower()
    if want in ("comfyui", "gemini"):
        pref = want
    use_comfy = settings.comfyui_url and pref in ("auto", "comfyui")
    if use_comfy and pref == "auto":
        try:
            from ..services import comfyui as _cf
            have = await _cf.video_files_available()
            use_comfy = any(_cf.VIDEO_PRESETS.get(settings.comfyui_video_model or "wan22-5b", {}).get("unet", "wan2.2") in h for h in have)
        except Exception:
            use_comfy = False
    if use_comfy:
        try:
            from ..services import comfyui as _cf
            start = None
            fid = args.get("image_file_id")
            if fid:
                asset_in = await ctx.db.get(FileAsset, str(fid))
                if asset_in and asset_in.family_id == ctx.user.family_id and asset_in.path:
                    start = Path(asset_in.path).read_bytes()
            data, label = await _cf.generate_video(prompt, args.get("aspect_ratio") or "16:9", start)
            asset = await _save_generated(ctx, data, "mp4", "video/mp4", "video")
        except Exception as e:
            log.exception("Generazione video (ComfyUI) fallita")
            return ToolResult(f"Generazione video fallita (comfyui): {type(e).__name__}: {e}", is_error=True)
        return ToolResult(f"Video generato con {label} e mostrato all'utente (id {asset.id}).",
                          artifacts=[{"type": "video", "file_id": asset.id, "url": f"/files/{asset.id}", "mime": "video/mp4"}],
                          usage={"provider": "comfyui", "model": label, "detail": "video"})
    if not settings.gemini_api_key:
        return ToolResult("Generazione video non disponibile: serve ComfyUI con il modello Wan 2.2 oppure una chiave Gemini (Veo).", is_error=True)
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        veo_model = await _resolve_veo_model(client)
        op = await client.aio.models.generate_videos(
            model=veo_model, prompt=prompt,
            config=types.GenerateVideosConfig(aspect_ratio=args.get("aspect_ratio") or "16:9", number_of_videos=1))
        for _ in range(60):  # max ~10 minuti
            if op.done:
                break
            await asyncio.sleep(10)
            op = await client.aio.operations.get(op)
        if not op.done or not op.response or not op.response.generated_videos:
            return ToolResult("Timeout o nessun video generato", is_error=True)
        video = op.response.generated_videos[0].video
        data = await asyncio.to_thread(lambda: client.files.download(file=video))
        if not data:
            data = video.video_bytes
        asset = await _save_generated(ctx, data, "mp4", "video/mp4", "video")
    except Exception as e:
        log.exception("Generazione video fallita")
        return ToolResult(f"Generazione video fallita: {type(e).__name__}: {e}", is_error=True)
    return ToolResult(f"Video generato e mostrato all'utente (id {asset.id}).",
                      artifacts=[{"type": "video", "file_id": asset.id, "url": f"/files/{asset.id}", "mime": "video/mp4"}],
                      usage={"provider": "gemini", "model": settings.video_model, "detail": "video 8s"})
