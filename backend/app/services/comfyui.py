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

settings = get_settings()

PRESETS: dict[str, dict] = {
    # nome → (tipo, file modello, passi, cfg/guidance)
    "flux-dev": {"kind": "flux", "unet": "flux1-dev.safetensors", "steps": 20, "guidance": 3.5},
    "flux-schnell": {"kind": "flux", "unet": "flux1-schnell.safetensors", "steps": 4, "guidance": 1.0},
    "sdxl": {"kind": "ckpt", "ckpt": "sd_xl_base_1.0.safetensors", "steps": 28, "cfg": 6.0, "vae": "sdxl_vae.safetensors"},
    "sd35": {"kind": "sd35", "ckpt": "sd3.5_large.safetensors", "steps": 28, "cfg": 4.0},
}


def _flux_workflow(p: dict, prompt: str, w: int, h: int, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5xxl_fp16.safetensors", "clip_name2": "clip_l.safetensors", "type": "flux"}},
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


def build_workflow(prompt: str, size: str, negative: str = "") -> tuple[dict, str]:
    w, h = (int(x) for x in (size or "1024x1024").lower().split("x"))
    w, h = max(256, min(w, 2048)) // 16 * 16, max(256, min(h, 2048)) // 16 * 16
    seed = random.randint(0, 2**31 - 1)
    name = (settings.comfyui_model or "flux-dev").strip()
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
    base = settings.comfyui_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{base}/object_info/CheckpointLoaderSimple")
        r.raise_for_status()
        ckpts = r.json()["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        r2 = await c.get(f"{base}/object_info/UNETLoader")
        unets = r2.json()["UNETLoader"]["input"]["required"]["unet_name"][0] if r2.status_code == 200 else []
        r3 = await c.get(f"{base}/system_stats")
        stats = r3.json() if r3.status_code == 200 else {}
    return {"checkpoints": ckpts, "unets": unets, "stats": stats}


async def generate(prompt: str, size: str = "1024x1024", negative: str = "", timeout_s: int = 300) -> tuple[bytes, str]:
    base = settings.comfyui_url.rstrip("/")
    wf, label = build_workflow(prompt, size, negative)
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
                raise RuntimeError(f"timeout dopo {timeout_s}s (modello in caricamento? riprova)")
