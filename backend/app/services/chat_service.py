"""Loop agentico: provider LLM + tool + policy famiglia, con streaming di eventi verso il client."""
from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Conversation, FileAsset, Message, Project, Role, User
from ..policy.permissions import (
    TOOL_ALIASES,
    check_daily_quota,
    check_time_window,
    effective_policy,
    log_usage,
    system_prompt_for,
    tool_allowed,
)
from ..policy.safety import CHILD_BLOCK_MESSAGE, check_text
from ..providers.registry import available_providers, get_provider
from ..security.sessions import user_has_passkey
from ..services import rag
from ..tools.documents import extract_text
from ..tools.mcp_client import mcp_manager
from ..tools.registry import ToolContext, all_tools, get_tool

log = logging.getLogger(__name__)
settings = get_settings()
MAX_TOOL_ROUNDS = 8
INLINE_DOC_CHARS = settings.rag_inline_max_chars


def sse(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, default=str)


async def _hydrate(blocks: list[dict], db: AsyncSession) -> list[dict]:
    """Carica i dati base64 delle immagini referenziate per file_id (solo per il provider)."""
    out = []
    for b in blocks:
        if b.get("type") == "image" and b.get("file_id") and not b.get("data"):
            asset = await db.get(FileAsset, b["file_id"])
            if asset and Path(asset.path).exists():
                out.append({"type": "image", "mime": asset.mime, "data": base64.b64encode(Path(asset.path).read_bytes()).decode()})
            continue
        if b.get("type") in ("image", "text", "tool_use", "tool_result"):
            out.append(b)
    return out


def repair_history(hist: list[dict]) -> list[dict]:
    """Rende la cronologia coerente per tutti i provider: ogni tool_use deve avere il suo tool_result nel
    messaggio successivo (turni interrotti), e nessun tool_result deve restare senza tool_use."""
    out: list[dict] = []
    pending: list[dict] = []   # tool_use in attesa di risultato
    for m in hist:
        if m["role"] == "tool":
            ids = {tu["id"] for tu in pending}
            kept = [b for b in m["content"] if b.get("type") == "tool_result" and b.get("tool_use_id") in ids]
            answered = {b["tool_use_id"] for b in kept}
            for tu in pending:
                if tu["id"] not in answered:
                    kept.append({"type": "tool_result", "tool_use_id": tu["id"], "name": tu["name"],
                                 "content": "(esecuzione interrotta: nessun risultato)", "is_error": True})
            pending = []
            if kept:
                out.append({"role": "tool", "content": kept})
            continue
        if pending:  # l'assistente aveva chiamato tool ma non e' seguito un messaggio tool
            out.append({"role": "tool", "content": [
                {"type": "tool_result", "tool_use_id": tu["id"], "name": tu["name"],
                 "content": "(esecuzione interrotta: nessun risultato)", "is_error": True} for tu in pending]})
            pending = []
        if m["role"] == "assistant":
            pending = [b for b in m["content"] if b.get("type") == "tool_use"]
            if not m["content"]:
                continue
        out.append(m)
    if pending:  # cronologia che termina con tool_use senza risultato
        out.append({"role": "tool", "content": [
            {"type": "tool_result", "tool_use_id": tu["id"], "name": tu["name"],
             "content": "(esecuzione interrotta: nessun risultato)", "is_error": True} for tu in pending]})
    # il primo messaggio deve essere dell'utente
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


async def build_history(conv: Conversation, db: AsyncSession) -> list[dict]:
    msgs = (await db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at))).scalars().all()
    hist = []
    for m in msgs:
        blocks = await _hydrate(m.content, db)
        if blocks:
            hist.append({"role": m.role, "content": blocks})
    return repair_history(hist)


async def build_system_prompt(user: User, conv: Conversation, db: AsyncSession) -> str:
    parts = [system_prompt_for(user)]
    if conv.project_id:
        proj = await db.get(Project, conv.project_id)
        if proj:
            parts.append(f"\n# Progetto: {proj.name}\n{proj.description}\n\nIstruzioni del progetto:\n{proj.instructions}")
            files = (await db.execute(select(FileAsset).where(FileAsset.project_id == proj.id))).scalars().all()
            if files:
                parts.append("File del progetto (cerca con search_documents, oppure leggi per intero con read_document):\n" +
                             "\n".join(f"- {f.filename} (id: {f.id}, {f.chunk_count} parti indicizzate)" for f in files))
    parts.append("\nQuando generi un'immagine o un video, l'utente lo vede automaticamente: non inventare link.")
    parts.append(
        "\n# Coding\n"
        "- Per pagine web, giochi, app HTML/CSS/JS, grafica SVG, diagrammi o programmi completi usa create_artifact: "
        "l'utente li vede in un pannello con anteprima live (HTML e SVG eseguiti nel browser). Per modifiche successive usa "
        "update_artifact (preferibilmente con replacements mirati) invece di ricreare l'artifact.\n"
        "- Per calcoli, analisi dati, grafici e per verificare che un programma funzioni usa run_code (sandbox senza internet); "
        "i file prodotti (png, csv…) vengono mostrati all'utente. Se l'esecuzione fallisce, correggi e riprova.\n"
        "- Brevi frammenti di codice o spiegazioni vanno direttamente nel messaggio con blocchi ```lingua```.")
    return "\n".join(parts)


async def prepare_user_blocks(text: str, file_ids: list[str], user: User, db: AsyncSession) -> list[dict]:
    blocks: list[dict] = []
    if text.strip():
        blocks.append({"type": "text", "text": text})
    for fid in file_ids:
        asset = await db.get(FileAsset, fid)
        if not asset or asset.family_id != user.family_id:
            continue
        if asset.mime.startswith("image/"):
            blocks.append({"type": "image", "file_id": asset.id, "mime": asset.mime, "filename": asset.filename})
        else:
            if asset.extracted_text is None:
                asset.extracted_text = extract_text(Path(asset.path), asset.mime) or ""
            txt = asset.extracted_text or ""
            if 0 < len(txt) <= INLINE_DOC_CHARS:
                blocks.append({"type": "text", "text": f"[Allegato: {asset.filename} (id {asset.id})]\n{txt}", "attachment": asset.id})
            else:
                blocks.append({"type": "text", "attachment": asset.id,
                               "text": f"[Allegato: {asset.filename} (id {asset.id}) — documento lungo: usa search_documents "
                                       f"per cercare i passaggi rilevanti o read_document per leggerlo per intero]"})
    await db.commit()
    return blocks


def resolve_provider_model(user: User, policy: dict, provider_id: str | None, model: str | None,
                           conv: Conversation | None = None) -> tuple[str, str]:
    """Bambini: provider e modello fissati dal genitore. Adulti: scelta libera tra i provider consentiti."""
    if user.role == Role.child:
        pid = policy.get("provider") or (conv.provider if conv else None)
        if pid not in policy["allowed_providers"]:
            pid = next((p for p in policy["allowed_providers"] if p in {x["id"] for x in available_providers()}), None)
        provider = get_provider(pid)
        chosen = policy.get("model") or provider.default_model
        known = {m["id"] for m in provider.models()}
        return provider.id, (chosen if not known or chosen in known else provider.default_model)
    pid = provider_id or (conv.provider if conv else None)
    if pid and pid not in policy["allowed_providers"] and pid != "mock":
        raise HTTPException(403, "Provider non consentito per questo utente")
    provider = get_provider(pid)
    chosen = model or (conv.model if conv and conv.provider == provider.id else "") or provider.default_model
    known = {m["id"] for m in provider.models()}
    if known and chosen not in known:
        chosen = provider.default_model   # es. modello ritirato dal provider
    return provider.id, chosen


async def run_turn(db: AsyncSession, user: User, conv: Conversation, text: str | None, file_ids: list[str],
                   provider_id: str | None, model: str | None, requested_tools: list[str] | None) -> AsyncIterator[str]:
    """Esegue un turno. Con text=None rigenera la risposta all'ultimo messaggio utente (es. dopo un cambio modello)."""
    policy = effective_policy(user)

    # ---- controlli preliminari ----
    # la passkey obbligatoria e' verificata a livello di sessione (require_auth + /me → pagina di registrazione)
    check_time_window(policy)
    await check_daily_quota(db, user, policy, "message")

    conv.provider, conv.model = resolve_provider_model(user, policy, provider_id, model, conv)
    provider = get_provider(conv.provider)
    model = conv.model

    if text is None:
        # ---- rigenerazione: elimina tutto ciò che segue l'ultimo messaggio utente ----
        msgs = (await db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at))).scalars().all()
        last_user = next((m for m in reversed(msgs) if m.role == "user"), None)
        if not last_user:
            raise HTTPException(400, "Nessun messaggio da rigenerare")
        removed = [m.id for m in msgs if m.created_at > last_user.created_at]
        for m in msgs:
            if m.id in removed:
                await db.delete(m)
        await db.commit()
        text = "".join(b.get("text", "") for b in last_user.content if b.get("type") == "text" and not b.get("attachment"))
        yield sse({"type": "regenerating", "removed": removed, "provider": provider.id, "model": model})
    else:
        # ---- messaggio utente + filtro contenuti ----
        user_blocks = await prepare_user_blocks(text, file_ids, user, db)
        safety = await check_text(text, policy)
        umsg = Message(conversation_id=conv.id, author_id=user.id, role="user", content=user_blocks,
                       flagged=safety.flagged, flag_reason=safety.reason)
        db.add(umsg)
        if conv.title == "Nuova chat" and text.strip():
            conv.title = text.strip()[:60]
        await db.commit()
        yield sse({"type": "user_message", "message": _msg_out(umsg)})

        if safety.block:
            amsg = Message(conversation_id=conv.id, role="assistant", content=[{"type": "text", "text": CHILD_BLOCK_MESSAGE}],
                           flagged=True, flag_reason="risposta bloccata")
            db.add(amsg)
            await db.commit()
            yield sse({"type": "text_delta", "text": CHILD_BLOCK_MESSAGE})
            yield sse({"type": "done", "message": _msg_out(amsg)})
            return

    # ---- tool consentiti ----
    tools = []
    for name, t in all_tools().items():
        if not tool_allowed(policy, name) or not mcp_manager.allowed_for(user.role, name):
            continue
        if requested_tools is not None:
            group = "mcp" if name.startswith("mcp__") else TOOL_ALIASES.get(name, name)
            if name not in requested_tools and group not in requested_tools:
                continue
        tools.append(t.spec)

    system = await build_system_prompt(user, conv, db)
    # RAG: recupero automatico dei passaggi pertinenti dai documenti del progetto / della chat
    if text.strip():
        try:
            hits = await rag.search(db, text, user.family_id,
                                    project_ids=[conv.project_id] if conv.project_id else None,
                                    conversation_ids=[conv.id])
            if hits:
                system += ("\n\n# Estratti dai documenti dell'utente pertinenti alla richiesta corrente\n"
                           "Usali se rispondono alla domanda e cita il nome del file; se non bastano usa search_documents.\n\n"
                           + rag.format_hits(hits))
                yield sse({"type": "rag", "hits": [{"file_id": h.file_id, "filename": h.filename, "idx": h.idx,
                                                   "score": h.score} for h in hits]})
        except Exception as e:
            log.warning("RAG non disponibile: %s", e)
    history = await build_history(conv, db)
    ctx = ToolContext(user=user, policy=policy, db=db, conversation_id=conv.id, project_id=conv.project_id)
    total_usage = {"input_tokens": 0, "output_tokens": 0}

    for _round in range(MAX_TOOL_ROUNDS + 1):
        text_acc = ""
        tool_uses: list[dict] = []
        try:
            async for ev in provider.stream(model, system, history, tools):
                if ev.type == "text_delta":
                    text_acc += ev.text
                    yield sse({"type": "text_delta", "text": ev.text})
                elif ev.type == "tool_use" and ev.tool_use:
                    tool_uses.append(ev.tool_use)
                elif ev.type == "usage":
                    total_usage["input_tokens"] += ev.usage.get("input_tokens", 0) or 0
                    total_usage["output_tokens"] += ev.usage.get("output_tokens", 0) or 0
        except Exception as e:
            log.exception("Errore provider")
            err = f"Errore del provider {provider.label}: {e}"
            amsg = Message(conversation_id=conv.id, role="assistant", content=[{"type": "text", "text": text_acc + f"\n\n⚠️ {err}"}])
            db.add(amsg)
            await db.commit()
            yield sse({"type": "error", "error": err})
            yield sse({"type": "done", "message": _msg_out(amsg)})
            return

        blocks: list[dict] = []
        if text_acc:
            blocks.append({"type": "text", "text": text_acc})
        blocks += [{"type": "tool_use", **tu} for tu in tool_uses]
        amsg = Message(conversation_id=conv.id, role="assistant", content=blocks)
        db.add(amsg)
        await db.commit()
        history.append({"role": "assistant", "content": blocks})

        if not tool_uses or _round == MAX_TOOL_ROUNDS:
            # risposta finale
            if policy.get("moderation") and text_acc:
                out_safety = await check_text(text_acc, policy)
                if out_safety.flagged:
                    amsg.flagged, amsg.flag_reason = True, "output: " + out_safety.reason
            amsg.usage = total_usage
            await db.commit()
            await log_usage(db, user, "message", provider.id, model, total_usage["input_tokens"], total_usage["output_tokens"])
            yield sse({"type": "done", "message": _msg_out(amsg)})
            return

        # ---- esecuzione tool ----
        results: list[dict] = []
        try:
          for tu in tool_uses:
              yield sse({"type": "tool_start", "id": tu["id"], "name": tu["name"], "input": tu["input"]})
              tool = get_tool(tu["name"])
              if not tool or not tool_allowed(policy, tu["name"]):
                  res_content, is_err, artifacts = "Strumento non disponibile", True, None
              else:
                  try:
                      await check_daily_quota(db, user, policy, tool.usage_kind)
                      r = await tool.fn(tu["input"] or {}, ctx)
                      res_content, is_err, artifacts = r.content, r.is_error, r.artifacts
                      if not is_err:
                          await log_usage(db, user, tool.usage_kind, provider.id, model, detail=tu["name"])
                  except HTTPException as he:
                      res_content, is_err, artifacts = he.detail, True, None
                  except Exception as e:
                      log.exception("Errore tool %s", tu["name"])
                      res_content, is_err, artifacts = f"Errore: {e}", True, None
              if not (res_content or "").strip():
                  res_content = "(il tool non ha restituito alcun dettaglio)" if is_err else "(nessun output)"
              if is_err:
                  log.warning("Tool %s fallito per %s: %s", tu["name"], user.username, res_content[:500])
              block = {"type": "tool_result", "tool_use_id": tu["id"], "name": tu["name"], "content": res_content[:50_000],
                       "is_error": is_err, "artifacts": artifacts or []}
              results.append(block)
              yield sse({"type": "tool_result", **block, "content": res_content[:800]})
        finally:
            # anche se lo stream viene interrotto (stop dell'utente), lascia la cronologia coerente
            done_ids = {r["tool_use_id"] for r in results}
            for tu in tool_uses:
                if tu["id"] not in done_ids:
                    results.append({"type": "tool_result", "tool_use_id": tu["id"], "name": tu["name"],
                                    "content": "(esecuzione interrotta)", "is_error": True, "artifacts": []})
            if results:
                db.add(Message(conversation_id=conv.id, role="tool", content=results))
                await db.commit()
        history.append({"role": "tool", "content": results})


def _msg_out(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "author_id": m.author_id, "content": m.content,
            "created_at": m.created_at, "flagged": m.flagged, "usage": m.usage or {}}
