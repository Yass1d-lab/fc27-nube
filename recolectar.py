"""Visita las paginas de urls.txt con 3 s de pausa y guarda su texto y enlaces.
Primero las paginas base (club, TOTW, promos, fodder, FUTWIZ) -> analisis para la tarea de Claude;
despues las paginas 'amp' (listado amplio de jugadores) -> alertas propias por Telegram.
Se detiene si detecta Cloudflare / 429 / 403. No intenta esquivar nada."""
import datetime, os, re, sys, time
from playwright.sync_api import sync_playwright
from comun import BASE, NUBE, telegram, cfg

# Prioridad baja: que el script no te quite rendimiento mientras juegas (Windows; si falla, sigue normal)
try:
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
except Exception:
    pass

PAUSA = 3
BLOQUEO = os.path.join(BASE, "bloqueo.txt")
MARCAS = ("just a moment", "attention required", "verify you are human", "cf-challenge", "checking your browser")

if os.path.exists(BLOQUEO) and time.time() - os.path.getmtime(BLOQUEO) < 110 * 60:   # 110 min: la corrida de +2 h ya no se salta
    print("Bloqueo reciente: no se intenta de nuevo todavia.")
    sys.exit(0)

paginas = []
for linea in open(os.path.join(BASE, "urls.txt"), encoding="utf-8-sig"):
    linea = linea.strip()
    if linea and not linea.startswith("#") and "|" in linea:
        n, u = linea.split("|", 1)
        paginas.append((n.strip(), u.strip()))
if NUBE:   # en la nube no hay sesion de FUT.GG: GG Club solo se lee desde la PC
    paginas = [p for p in paginas if not p[0].startswith("club") and "gg-club" not in p[1]]
base = [p for p in paginas if not p[0].startswith("amp")]
amp = [p for p in paginas if p[0].startswith("amp")]

ahora = datetime.datetime.now()
carpeta = os.path.join(BASE, "datos", ahora.strftime("%Y-%m-%d_%H%M"))
os.makedirs(carpeta, exist_ok=True)
estado = {"ok": 0, "motivo": None, "fallos": 0, "solo_error": False}
print(f"=== INICIO {ahora:%Y-%m-%d %H:%M:%S} ===")

def necesita_sync(texto):
    """True si GG Club lleva 3 horas o mas (o dias) sin sincronizar con EA."""
    m = re.search(r"Last synced\s+(a|an|\d+)\s+(second|minute|hour|day)s?\s+ago", texto or "", re.I)
    if not m: return False
    n = 1 if m.group(1).lower() in ("a", "an") else int(m.group(1))
    u = m.group(2).lower()
    return u == "day" or (u == "hour" and n >= 3)

def leer(page, lista):
    for nombre, url in lista:
        esamp = nombre.startswith("amp")
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = resp.status if resp else 0
            page.wait_for_timeout(2500)
            if nombre == "club_transferlist":      # unico clic permitido en GG Club: Sync Club (lectura oficial de EA)
                try:
                    if necesita_sync(page.inner_text("body")):
                        boton = page.get_by_text("Sync Club", exact=True).first
                        if boton.count() and boton.is_visible() and boton.is_enabled():
                            boton.click(); print("Sync Club pulsado")
                            page.wait_for_timeout(15000)
                            page.reload(wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(2500)
                        else:
                            print("Sync Club: boton no disponible, sigo sin sincronizar")
                except Exception as e:
                    print("Sync Club fallo (sigo sin sincronizar):", e)
            vueltas = 14 if nombre.startswith("futwiz") else (3 if esamp else 4)
            for _ in range(vueltas):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1200 if nombre.startswith("futwiz") else 700)
            texto = page.inner_text("body")
            largo = 400 if nombre.startswith("club_players") else 80   # en el club el precio va al final del texto
            enlaces = page.eval_on_selector_all(
                "a[href]", "(els, n) => els.map(e => ({h: e.getAttribute('href'), t: (e.innerText||'').trim().slice(0,n), a: (e.querySelector('img')||{}).alt||''}))", largo)
            titulo = (page.title() or "").lower()
        except Exception as e:                 # un error suelto no es un bloqueo: se salta la pagina
            estado["fallos"] += 1
            print(f"ERROR {nombre}: {type(e).__name__}: {str(e)[:120]}")
            if estado["fallos"] >= 3:
                estado["motivo"] = f"3 paginas con error (ultima: {nombre})"; estado["solo_error"] = True; return False
            time.sleep(PAUSA); continue
        if status in (403, 429, 503) or any(m in titulo or m in texto[:3000].lower() for m in MARCAS):
            estado["motivo"] = f"bloqueo/Cloudflare en {nombre} (HTTP {status})"; return False
        for e in enlaces:                      # TOTW nuevo: se agrega solo
            m = re.search(r"/squads/team-of-the-week/totw-(\d+)/?", e["h"] or "")
            if m and not esamp:
                num = int(m.group(1)); tn = f"TOTW{num}"
                topes = [int(re.sub(r"\D", "", n)) for n, _ in lista if re.fullmatch(r"TOTW\d+", n)] or [0]
                if tn not in [n for n, _ in lista] and num > max(topes):
                    lista.append((tn, "https://www.fut.gg" + e["h"] if e["h"].startswith("/") else e["h"]))
        if not esamp:
            with open(os.path.join(carpeta, f"{nombre}.txt"), "w", encoding="utf-8") as f:
                f.write(f"#URL {url}\n#HORA {datetime.datetime.now().isoformat()}\n{texto}")
        with open(os.path.join(carpeta, f"{nombre}.links.txt"), "w", encoding="utf-8") as f:
            for e in enlaces:
                f.write(f"{e['h']} | {e['t'].replace(chr(10), ' / ')} | {e['a']}\n")
        estado["ok"] += 1
        print(f"OK {nombre}")
        time.sleep(PAUSA)
    return True

import analizar
with sync_playwright() as p:
    # ventana = oculta (por defecto, sin ventana de Chrome) | visible. Se cambia en opciones.ini, seccion [ventana], clave modo.
    oculta = cfg().get("ventana", "modo", fallback="oculta").strip().lower() != "visible"
    ctx = p.chromium.launch_persistent_context(os.path.join(BASE, "perfil"), headless=oculta,
                                               args=[] if oculta else ["--start-minimized"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ok_base = leer(page, base)
    if ok_base:
        try: analizar.main(carpeta)
        except Exception as e:
            telegram(f"⚠️ FC27 script: lei las paginas pero fallo el analisis: {e}"); print("Fallo el analisis:", e)
        if amp:
            ok_amp = leer(page, amp)
            try: analizar.amplio(carpeta)
            except Exception as e: print("Fallo el analisis amplio:", e)
            if ok_amp:   # confirma las candidatas en la pagina de cada carta (solo lectura, 4 s entre paginas)
                try:
                    import confirmar
                    motivo = confirmar.confirmar(page)
                    if motivo: estado["motivo"] = motivo
                except Exception as e: print("Fallo confirmar:", e)
    ctx.close()

# Limpieza: borra carpetas de datos de mas de 7 dias (los historiales viven en estado.json y amplio.json)
try:
    import shutil
    lim = time.time() - 7 * 86400
    dd = os.path.join(BASE, "datos")
    for d in os.listdir(dd):
        p = os.path.join(dd, d)
        if os.path.isdir(p) and os.path.getmtime(p) < lim:
            shutil.rmtree(p, ignore_errors=True)
except Exception as e:
    print("Limpieza de datos fallo:", e)

total = len(paginas)
if estado["motivo"]:
    if not estado["solo_error"]: open(BLOQUEO, "w").write(estado["motivo"])   # pausa de 2 h solo por bloqueo real
    telegram(f"⚠️ FC27 script detenido: {estado['motivo']}. Recolectadas {estado['ok']}/{total}. No reintento por 2 h.")
    print("DETENIDO:", estado["motivo"])
else:
    print(f"Listo: {estado['ok']}/{total} paginas.")
print(f"=== FIN {datetime.datetime.now():%H:%M:%S} · {int((datetime.datetime.now() - ahora).total_seconds())} s · fallos {estado['fallos']} ===")
