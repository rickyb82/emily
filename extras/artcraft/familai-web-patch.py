#!/usr/bin/env python3
"""Piccola patch alle app web ArtCraft (apps/<app>-web) per integrarle in FamilAI.

Uso: familai-web-patch.py <cartella-repo> <app>      (app: wordcraft | gridcraft | pdfcraft)

Aggiunge due parametri all'URL della pagina:
  ?open=<url>&name=<file>   apre il documento scaricandolo dal server (con i cookie di sessione)
  ?save=<url>               File > Salva / Esporta spediscono il file al server con una POST invece di scaricarlo
Senza questi parametri l'app si comporta come l'originale. Eseguito dal Dockerfile.web sulla copia del repository;
si ferma con errore se il sorgente e' cambiato e gli ancoraggi non si trovano piu' (aggiornare gli ancoraggi qui).
"""
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
app = sys.argv[2] if len(sys.argv) > 2 else "wordcraft"
web_rs = root / f"apps/{app}-web/src/web.rs"
cargo = root / f"apps/{app}-web/Cargo.toml"
UI_CRATE = f"{app}_ui_egui"

COMMON = r'''
    fn param(key: &str) -> Option<String> {
        let search = web_sys::window().and_then(|w| w.location().search().ok())?;
        let params = web_sys::UrlSearchParams::new_with_str(&search).ok()?;
        params.get(key).filter(|v| !v.is_empty())
    }

    pub fn save_url() -> Option<String> {
        param("save")
    }

    pub fn open_from_query(inbox: Inbox, ctx: egui::Context) {
        let Some(url) = param("open") else {
            return;
        };
        let name = param("name").unwrap_or_else(|| url.rsplit('/').next().unwrap_or("document").to_string());
        wasm_bindgen_futures::spawn_local(async move {
            match fetch_bytes(&url).await {
                Ok(bytes) => {
                    inbox.lock().unwrap_or_else(|e| e.into_inner()).push((name, bytes));
                    ctx.request_repaint();
                }
                Err(e) => log::error!("FamilAI: couldn't open {url}: {e}"),
            }
        });
    }

    async fn fetch_bytes(url: &str) -> Result<Vec<u8>, String> {
        let js = |e: wasm_bindgen::JsValue| format!("{e:?}");
        let window = web_sys::window().ok_or("no window")?;
        let opts = web_sys::RequestInit::new();
        opts.set_credentials(web_sys::RequestCredentials::Include);
        let resp = wasm_bindgen_futures::JsFuture::from(window.fetch_with_str_and_init(url, &opts)).await.map_err(js)?;
        let resp: web_sys::Response = resp.dyn_into().map_err(|_| "not a Response".to_string())?;
        if !resp.ok() {
            return Err(format!("HTTP {}", resp.status()));
        }
        let buf = wasm_bindgen_futures::JsFuture::from(resp.array_buffer().map_err(js)?).await.map_err(js)?;
        Ok(js_sys::Uint8Array::new(&buf).to_vec())
    }

    async fn post_bytes(url: &str, name: &str, bytes: &[u8]) -> Result<(), String> {
        let js = |e: wasm_bindgen::JsValue| format!("{e:?}");
        let window = web_sys::window().ok_or("no window")?;
        let headers = web_sys::Headers::new().map_err(js)?;
        headers.set("Content-Type", "application/octet-stream").map_err(js)?;
        let encoded = js_sys::encode_uri_component(name).as_string().unwrap_or_default();
        headers.set("X-Filename", &encoded).map_err(js)?;
        let opts = web_sys::RequestInit::new();
        opts.set_method("POST");
        opts.set_credentials(web_sys::RequestCredentials::Include);
        opts.set_headers(&headers);
        opts.set_body(&js_sys::Uint8Array::from(bytes));
        let resp = wasm_bindgen_futures::JsFuture::from(window.fetch_with_str_and_init(url, &opts)).await.map_err(js)?;
        let resp: web_sys::Response = resp.dyn_into().map_err(|_| "not a Response".to_string())?;
        if !resp.ok() {
            return Err(format!("HTTP {}", resp.status()));
        }
        Ok(())
    }
}
'''

# WordCraft tiene il conto dei salvataggi in corso (PickerSaves); GridCraft no.
SAVE_WORDCRAFT = r'''
    pub fn save_remote(saves: &Rc<PickerSaves>, ctx: &egui::Context, url: &str, name: &str, bytes: &[u8]) -> Result<(), String> {
        let saves = saves.clone();
        let ctx = ctx.clone();
        let url = url.to_string();
        let name = name.to_string();
        let bytes = bytes.to_vec();
        saves.pending.set(saves.pending.get().saturating_add(1));
        wasm_bindgen_futures::spawn_local(async move {
            match post_bytes(&url, &name, &bytes).await {
                Ok(()) => log::info!("FamilAI: saved {name}"),
                Err(e) => {
                    log::error!("FamilAI: couldn't save {name}: {e}");
                    saves.unsaved.borrow_mut().push((name, Some(e)));
                }
            }
            saves.pending.set(saves.pending.get().saturating_sub(1));
            ctx.request_repaint();
        });
        Ok(())
    }
'''
SAVE_SIMPLE = r'''
    pub fn save_remote(url: &str, name: &str, bytes: &[u8]) -> Result<(), String> {
        let url = url.to_string();
        let name = name.to_string();
        let bytes = bytes.to_vec();
        wasm_bindgen_futures::spawn_local(async move {
            match post_bytes(&url, &name, &bytes).await {
                Ok(()) => log::info!("FamilAI: saved {name}"),
                Err(e) => log::error!("FamilAI: couldn't save {name}: {e}"),
            }
        });
        Ok(())
    }
'''

HEAD_WORDCRAFT = '''

/// Integrazione FamilAI: `?open=<url>&name=<file>` apre un documento preso dal server;
/// `?save=<url>` fa si' che Salva/Esporta spediscano il file al server (POST) invece di scaricarlo.
mod familai {
    use std::rc::Rc;

    use wasm_bindgen::JsCast as _;
    use wordcraft_ui_egui::Inbox;

    use super::PickerSaves;
'''
HEAD_SIMPLE = f'''

/// Integrazione FamilAI: `?open=<url>&name=<file>` apre un file preso dal server;
/// `?save=<url>` fa si' che Salva/Esporta spediscano il file al server (POST) invece di scaricarlo.
mod familai {{
    use wasm_bindgen::JsCast as _;
    use {UI_CRATE}::Inbox;
'''

FEATURES = ', "UrlSearchParams", "RequestInit", "RequestCredentials", "Response", "Headers"]'


def patch(path: Path, old: str, new: str, label: str) -> None:
    s = path.read_text()
    if new in s:
        print(f"  = {label}: gia' applicata")
        return
    if old not in s:
        sys.exit(f"!! {label}: ancoraggio non trovato in {path} ({app} e' cambiato: aggiornare la patch)")
    path.write_text(s.replace(old, new, 1))
    print(f"  + {label}")


print(f"Patch FamilAI per {app} web in {root}")
if app == "wordcraft":
    patch(cargo, '"MediaQueryList"]', '"MediaQueryList"' + FEATURES, "Cargo.toml: feature web-sys")
    patch(web_rs,
          "                    if let Err(e) = listen_for_pasted_pictures(inbox.clone(), cc.egui_ctx.clone()) {\n",
          "                    familai::open_from_query(inbox.clone(), cc.egui_ctx.clone());\n"
          "                    if let Err(e) = listen_for_pasted_pictures(inbox.clone(), cc.egui_ctx.clone()) {\n",
          "web.rs: ?open=")
    patch(web_rs,
          '    let window = web_sys::window().ok_or("no window")?;\n\n    // On browsers supporting the File System Access API',
          '    let window = web_sys::window().ok_or("no window")?;\n'
          '    if let Some(save_url) = familai::save_url() {\n'
          '        return familai::save_remote(saves, ctx, &save_url, &name, bytes);\n'
          '    }\n\n    // On browsers supporting the File System Access API',
          "web.rs: ?save=")
    patch(web_rs, "\nfn mime_for(", HEAD_WORDCRAFT + SAVE_WORDCRAFT + COMMON + "\nfn mime_for(", "web.rs: modulo familai")
elif app == "gridcraft":
    patch(cargo, '"ClipboardItem", "Navigator"]', '"ClipboardItem", "Navigator"' + FEATURES, "Cargo.toml: feature web-sys")
    patch(web_rs,
          "                    let inbox: Inbox = Inbox::default();\n                    let mut session = Session::new();\n",
          "                    let inbox: Inbox = Inbox::default();\n"
          "                    familai::open_from_query(inbox.clone(), cc.egui_ctx.clone());\n"
          "                    let mut session = Session::new();\n",
          "web.rs: ?open=")
    patch(web_rs,
          'fn download(name: &str, bytes: &[u8]) -> Result<(), String> {\n'
          '    let js = |e: wasm_bindgen::JsValue| format!("{e:?}");\n'
          '    let window = web_sys::window().ok_or("no window")?;\n',
          'fn download(name: &str, bytes: &[u8]) -> Result<(), String> {\n'
          '    if let Some(save_url) = familai::save_url() {\n'
          '        return familai::save_remote(&save_url, name, bytes);\n'
          '    }\n'
          '    let js = |e: wasm_bindgen::JsValue| format!("{e:?}");\n'
          '    let window = web_sys::window().ok_or("no window")?;\n',
          "web.rs: ?save=")
    patch(web_rs, "\nfn mime_for(", HEAD_SIMPLE + SAVE_SIMPLE + COMMON + "\nfn mime_for(", "web.rs: modulo familai")
elif app == "pdfcraft":
    # PdfCraft ha gia' tutto: ?file=<url> apre dal server e ?host=parent spedisce i salvataggi alla pagina che lo
    # incornicia via postMessage (pdfcraft:save); FamilAI li riceve nella pagina Editor. Nessuna patch.
    print("  = pdfcraft: nessuna patch necessaria (?file= e ?host=parent sono nativi)")
else:
    sys.exit(f"!! app sconosciuta: {app}")
print("Patch completata.")
