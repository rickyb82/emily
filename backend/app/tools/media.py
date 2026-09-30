"""Generazione immagini (OpenAI gpt-image) e video (Gemini / Veo)."""
from __future__ import annotations

import asyncio
import base64
import uuid

from ..config import get_settings
from ..models import FileAsset
from .registry import ToolContext, ToolResult, register

settings = get_settings()

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
    "Genera un'immagine a partire da una descrizione testuale. Descrivi soggetto, stile e dettagli.",
    {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "Descrizione dell'immagine"},
        "size": {"type": "string", "enum": ["1024x1024", "1024x1536", "1536x1024"], "description": "Dimensione"}},
     "required": ["prompt"]},
    usage_kind="image",
)
async def generate_image(args: dict, ctx: ToolContext) -> ToolResult:
    if not settings.openai_api_key:
        return ToolResult("Generazione immagini non configurata (manca OPENAI_API_KEY)", is_error=True)
    prompt = str(args.get("prompt", "")).strip()
    if ctx.policy.get("moderation"):
        prompt = CHILD_PROMPT_PREFIX + prompt
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        r = await client.images.generate(model=settings.image_model, prompt=prompt,
                                         size=args.get("size") or "1024x1024", n=1)
        b64 = r.data[0].b64_json
        if not b64:
            return ToolResult("Il provider non ha restituito l'immagine", is_error=True)
        asset = await _save_generated(ctx, base64.b64decode(b64), "png", "image/png", "immagine")
    except Exception as e:
        return ToolResult(f"Generazione immagine fallita: {e}", is_error=True)
    url = f"/files/{asset.id}"
    return ToolResult(f"Immagine generata e mostrata all'utente (id {asset.id}). Descrivila brevemente.",
                      artifacts=[{"type": "image", "file_id": asset.id, "url": url, "mime": "image/png"}])


@register(
    "generate_video",
    "Genera un breve video (circa 8 secondi) da una descrizione testuale. L'operazione può richiedere qualche minuto.",
    {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "Descrizione della scena"},
        "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"], "description": "Formato"}},
     "required": ["prompt"]},
    usage_kind="video",
)
async def generate_video(args: dict, ctx: ToolContext) -> ToolResult:
    if not settings.gemini_api_key:
        return ToolResult("Generazione video non configurata (manca GEMINI_API_KEY)", is_error=True)
    prompt = str(args.get("prompt", "")).strip()
    if ctx.policy.get("moderation"):
        prompt = CHILD_PROMPT_PREFIX + prompt
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        op = await client.aio.models.generate_videos(
            model=settings.video_model, prompt=prompt,
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
        return ToolResult(f"Generazione video fallita: {e}", is_error=True)
    return ToolResult(f"Video generato e mostrato all'utente (id {asset.id}).",
                      artifacts=[{"type": "video", "file_id": asset.id, "url": f"/files/{asset.id}", "mime": "video/mp4"}])
