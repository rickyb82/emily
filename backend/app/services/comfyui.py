"""Client ComfyUI per la generazione immagini in casa (API HTTP: POST /prompt, GET /history, GET /view).
Workflow integrati per Flux.1 (unet + dual clip + vae) e SDXL/SD3.5 (checkpoint): niente da esportare dall'interfaccia.
Si puo' comunque fornire un workflow personalizzato in formato API (file JSON) con i segnaposto
{{PROMPT}} {{NEGATIVE}} {{WIDTH}} {{HEIGHT}} {{SEED}} {{STEPS}}."""
from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from pathlib import Path

import httpx

from ..config import get_settings
from .neturl import host_url

settings = get_settings()

PRESETS: dict[str, dict] = {
    # nome → (tipo, file modello, passi, cfg/guidance)
    "flux-dev": {"kind": "flux", "unet": "flux1-dev.safetensors", "steps": 20, "guidance": 3.5},
    "flux-schnell": {"kind": "flux", "unet": "flux1-schnell.safetensors", "steps": 4, "guidance": 1.0},
    "flux-dev-gguf": {"kind": "flux", "gguf": True, "unet": "flux1-dev-Q6_K.gguf", "t5": "t5-v1_1-xxl-encoder-Q8_0.gguf", "steps": 20, "guidance": 3.5},
    "flux-schnell-gguf": {"kind": "flux", "gguf": True, "unet": "flux1-schnell-Q8_0.gguf", "t5": "t5-v1_1-xxl-encoder-Q8_0.gguf", "steps": 4, "guidance": 1.0},
    "sdxl": {"kind": "ckpt", "ckpt": "sd_xl_base_1.0.safetensors", "steps": 28, "cfg": 6.0, "vae": "sdxl_vae.safetensors"},
    "sd35": {"kind": "sd35", "ckpt": "sd3.5_large.safetensors", "steps": 28, "cfg": 4.0},
}


def _flux_workflow(p: dict, prompt: str, w: int, h: int, seed: int) -> dict:
    if p.get("gguf"):
        # modelli quantizzati (nodo ComfyUI-GGUF): Flux in 24 GB di memoria (Mac Apple Silicon, GPU piccole)
        loader = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": p["unet"]}}
        clip = {"class_type": "DualCLIPLoaderGGUF", "inputs": {"clip_name1": p.get("t5", "t5-v1_1-xxl-encoder-Q8_0.gguf"), "clip_name2": "clip_l.safetensors", "type": "flux"}}
    else:
        loader = {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}}
        clip = {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5xxl_fp16.safetensors", "clip_name2": "clip_l.safetensors", "type": "flux"}}
    return {
        "1": loader,
        "2": clip,
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"guidance": p["guidance"], "conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "8": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": p["steps"], "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                                                   "denoise": 1.0, "model": ["1", 0], "positive": ["5", 0], "negative": ["7", 0], "latent_image": ["6", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "familai", "images": ["9", 0]}},
    }


def _ckpt_workflow(p: dict, prompt: str, negative: str, w: int, h: int, seed: int) -> dict:
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": p["ckpt"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage" if p["kind"] == "ckpt" else "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": p["steps"], "cfg": p["cfg"], "sampler_name": "dpmpp_2m" if p["kind"] == "ckpt" else "euler",
                                                   "scheduler": "karras" if p["kind"] == "ckpt" else "sgm_uniform", "denoise": 1.0,
                                                   "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "familai", "images": ["6", 0]}},
    }
    if p.get("vae"):
        wf["8"] = {"class_type": "VAELoader", "inputs": {"vae_name": p["vae"]}}
        wf["6"]["inputs"]["vae"] = ["8", 0]
    return wf


def _custom_workflow(path: str, prompt: str, negative: str, w: int, h: int, seed: int, steps: int) -> dict:
    raw = Path(path).read_text()
    for k, v in {"{{PROMPT}}": json.dumps(prompt)[1:-1], "{{NEGATIVE}}": json.dumps(negative)[1:-1], "{{WIDTH}}": str(w),
                 "{{HEIGHT}}": str(h), "{{SEED}}": str(seed), "{{STEPS}}": str(steps)}.items():
        raw = raw.replace(k, v)
    return json.loads(raw)


def build_workflow(prompt: str, size: str, negative: str = "", model_name: str | None = None) -> tuple[dict, str]:
    w, h = (int(x) for x in (size or "1024x1024").lower().split("x"))
    w, h = max(256, min(w, 2048)) // 16 * 16, max(256, min(h, 2048)) // 16 * 16
    seed = random.randint(0, 2**31 - 1)
    name = (model_name or settings.comfyui_model or "flux-dev").strip()
    if settings.comfyui_workflow and Path(settings.comfyui_workflow).exists():
        return _custom_workflow(settings.comfyui_workflow, prompt, negative, w, h, seed, 20), f"ComfyUI ({Path(settings.comfyui_workflow).name})"
    p = PRESETS.get(name)
    if not p:
        # nome di un checkpoint custom (es. juggernautXL_v9.safetensors) → workflow SDXL
        p = {"kind": "ckpt", "ckpt": name, "steps": 28, "cfg": 6.0}
    if p["kind"] == "flux":
        return _flux_workflow(p, prompt, w, h, seed), f"ComfyUI / {name}"
    neg = negative or "blurry, low quality, deformed, watermark, text"
    return _ckpt_workflow(p, prompt, neg, w, h, seed), f"ComfyUI / {name}"


def enabled() -> bool:
    return bool(settings.comfyui_url)


async def models_available() -> dict:
    """Elenco modelli presenti sul server (per la pagina admin e la prova di connessione)."""
    base = host_url(settings.comfyui_url).rstrip("/")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{base}/object_info/CheckpointLoaderSimple")
        r.raise_for_status()
        ckpts = r.json()["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        r2 = await c.get(f"{base}/object_info/UNETLoader")
        unets = r2.json()["UNETLoader"]["input"]["required"]["unet_name"][0] if r2.status_code == 200 else []
        r4 = await c.get(f"{base}/object_info/UnetLoaderGGUF")
        if r4.status_code == 200:
            unets = list(dict.fromkeys(unets + r4.json()["UnetLoaderGGUF"]["input"]["required"]["unet_name"][0]))
        r3 = await c.get(f"{base}/system_stats")
        stats = r3.json() if r3.status_code == 200 else {}
    return {"checkpoints": ckpts, "unets": unets, "stats": stats}


_avail_cache: dict = {"at": 0.0, "have": []}


async def _available_files() -> list[str]:
    if time.monotonic() - _avail_cache["at"] < 60 and _avail_cache["have"]:
        return _avail_cache["have"]
    try:
        info = await models_available()
        _avail_cache.update(at=time.monotonic(), have=info["checkpoints"] + info["unets"])
    except Exception:
        pass
    return _avail_cache["have"]


def _preset_ok(name: str, have: list[str]) -> bool:
    p = PRESETS.get(name)
    need = (p.get("unet") or p.get("ckpt")) if p else name
    return any(need in h for h in have)


async def resolve_model_name() -> str:
    """Il modello scelto, oppure il primo preset i cui file esistono davvero sul server (es. gguf scaricato sul Mac)."""
    name = (settings.comfyui_model or "flux-dev").strip()
    have = await _available_files()
    if not have or _preset_ok(name, have):
        return name
    for cand in ("flux-dev", "flux-dev-gguf", "flux-schnell", "flux-schnell-gguf", "sdxl", "sd35"):
        if _preset_ok(cand, have):
            return cand
    return name


async def generate(prompt: str, size: str = "1024x1024", negative: str = "", timeout_s: int | None = None) -> tuple[bytes, str]:
    timeout_s = timeout_s or int(settings.comfyui_timeout or 1800)
    base = host_url(settings.comfyui_url).rstrip("/")
    name = await resolve_model_name()
    wf, label = build_workflow(prompt, size, negative, model_name=name)
    client_id = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{base}/prompt", json={"prompt": wf, "client_id": client_id})
        if r.status_code >= 400:
            detail = r.text[:600]
            try:
                j = r.json()
                errs = j.get("node_errors") or {}
                if errs:
                    first = next(iter(errs.values()))
                    detail = "; ".join(e.get("message", "") + (" " + e.get("details", "") if e.get("details") else "") for e in first.get("errors", [])) or detail
                elif j.get("error"):
                    detail = j["error"].get("message", detail)
            except Exception:
                pass
            raise RuntimeError(f"ComfyUI ha rifiutato il workflow: {detail}")
        pid = r.json()["prompt_id"]
        t0 = time.monotonic()
        while True:
            await asyncio.sleep(1.5)
            h = await c.get(f"{base}/history/{pid}")
            data = h.json().get(pid) if h.status_code == 200 else None
            if data:
                st = data.get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError("errore in ComfyUI: " + ("; ".join(msgs) or "sconosciuto"))
                outputs = data.get("outputs", {})
                for node in outputs.values():
                    for img in node.get("images", []):
                        v = await c.get(f"{base}/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
                        v.raise_for_status()
                        return v.content, label
            if time.monotonic() - t0 > timeout_s:
                # non lasciamo il lavoro in coda a occupare la GPU
                try:
                    await c.post(f"{base}/interrupt")
                except Exception:
                    pass
                raise RuntimeError(f"timeout dopo {timeout_s}s: la generazione non e' finita (alza COMFYUI_TIMEOUT o usa un modello piu' leggero)")


# ------------------------------------------------------------------ video (Wan 2.2 5B TI2V: testo→video e immagine→video)
VIDEO_PRESETS: dict[str, dict] = {
    "wan22-5b": {"unet": "wan2.2_ti2v_5B_fp16.safetensors", "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae": "wan2.2_vae.safetensors",
                 "steps": 20, "cfg": 5.0, "shift": 8.0, "fps": 24},
}


def _wan_workflow(p: dict, prompt: str, negative: str, w: int, h: int, frames: int, seed: int, start_image: str | None) -> dict:
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip"], "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae"]}},
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"shift": p["shift"], "model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "7": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"width": w, "height": h, "length": frames, "batch_size": 1, "vae": ["3", 0]}},
        "8": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": p["steps"], "cfg": p["cfg"], "sampler_name": "uni_pc", "scheduler": "simple",
                                                   "denoise": 1.0, "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "CreateVideo", "inputs": {"fps": p["fps"], "images": ["9", 0]}},
        "11": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "familai/video", "format": "mp4", "codec": "h264", "video": ["10", 0]}},
    }
    if start_image:
        wf["12"] = {"class_type": "LoadImage", "inputs": {"image": start_image}}
        wf["7"]["inputs"]["start_image"] = ["12", 0]
    return wf


WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
                "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")


async def upload_image(data: bytes, name: str = "familai_start.png") -> str:
    base = host_url(settings.comfyui_url).rstrip("/")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{base}/upload/image", files={"image": (name, data, "image/png")}, data={"overwrite": "true"})
        r.raise_for_status()
        return r.json().get("name", name)


async def generate_video(prompt: str, aspect: str = "16:9", start_image_bytes: bytes | None = None,
                         timeout_s: int | None = None) -> tuple[bytes, str]:
    """Video con Wan 2.2 (5B) via ComfyUI. Dimensioni/durata da impostazioni (Mac: piccole; GPU grandi: 1280x704, 121 frame)."""
    timeout_s = timeout_s or int(settings.comfyui_video_timeout or 5400)
    base = host_url(settings.comfyui_url).rstrip("/")
    name = (settings.comfyui_video_model or "wan22-5b").strip()
    p = VIDEO_PRESETS.get(name) or VIDEO_PRESETS["wan22-5b"]
    try:
        w, h = (int(x) for x in (settings.comfyui_video_size or "832x480").lower().split("x"))
    except ValueError:
        w, h = 832, 480
    if aspect == "9:16" and w > h:
        w, h = h, w
    w, h = max(256, w) // 32 * 32, max(256, h) // 32 * 32
    frames = int(settings.comfyui_video_frames or 49)
    frames = max(9, (frames - 1) // 4 * 4 + 1)        # Wan: 4n+1
    seed = random.randint(0, 2**31 - 1)
    start = await upload_image(start_image_bytes) if start_image_bytes else None
    wf = _wan_workflow(p, prompt, WAN_NEGATIVE, w, h, frames, seed, start)
    client_id = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{base}/prompt", json={"prompt": wf, "client_id": client_id})
        if r.status_code >= 400:
            detail = r.text[:600]
            try:
                j = r.json()
                errs = j.get("node_errors") or {}
                if errs:
                    first = next(iter(errs.values()))
                    detail = "; ".join(e.get("message", "") + (" " + e.get("details", "") if e.get("details") else "") for e in first.get("errors", [])) or detail
            except Exception:
                pass
            raise RuntimeError(f"ComfyUI ha rifiutato il workflow video: {detail}")
        pid = r.json()["prompt_id"]
        t0 = time.monotonic()
        while True:
            await asyncio.sleep(3)
            hres = await c.get(f"{base}/history/{pid}")
            data = hres.json().get(pid) if hres.status_code == 200 else None
            if data:
                st = data.get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError("errore in ComfyUI: " + ("; ".join(msgs) or "sconosciuto"))
                for node in data.get("outputs", {}).values():
                    for key in ("video", "images", "gifs"):
                        for it in node.get(key, []) or []:
                            fn = it.get("filename", "")
                            if fn.lower().endswith((".mp4", ".webm", ".mov")):
                                v = await c.get(f"{base}/view", params={"filename": fn, "subfolder": it.get("subfolder", ""), "type": it.get("type", "output")})
                                v.raise_for_status()
                                return v.content, f"ComfyUI / {name} ({w}x{h}, {frames} frame)"
            if time.monotonic() - t0 > timeout_s:
                try:
                    await c.post(f"{base}/interrupt")
                except Exception:
                    pass
                raise RuntimeError(f"timeout dopo {timeout_s}s: il video non e' finito (alza COMFYUI_VIDEO_TIMEOUT o riduci frame/risoluzione)")


async def video_files_available() -> list[str]:
    base = host_url(settings.comfyui_url).rstrip("/")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{base}/object_info/UNETLoader")
        return r.json()["UNETLoader"]["input"]["required"]["unet_name"][0] if r.status_code == 200 else []
