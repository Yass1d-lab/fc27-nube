"""
leer_cartas.py - lee la pagina de una carta de FUT.GG (solo lectura, Playwright).
Uso suelto (doble clic en leer_cartas.bat, usa cartas.txt, una URL por linea, maximo 30):
    python leer_cartas.py --archivo cartas.txt
    python leer_cartas.py URL1 URL2 ...
Tambien lo usa confirmar.py (dentro de recolectar.py) con la misma pagina del navegador.

De cada carta saca (del endpoint /api/fut/player-prices/27/<id>/ que carga la propia pagina):
precio actual, ~100 ventas recientes con su precio real, subastas activas, y el rango del texto de la pagina.
Reglas: solo lee; no hace clic en nada; si ve Cloudflare/403/429 se detiene (no esquiva nada).
"""
import datetime, json, re, sys, time, pathlib

MAX_CARTAS = 30
PAUSA_S = 4
SALIDA = pathlib.Path("cartas_detalle.json")
MARCAS = ("just a moment", "attention required", "verify you are human", "cf-challenge", "checking your browser")


def num(s):
    return int(re.sub(r"[^\d]", "", s))


def _fecha(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def resumen_api(data):
    """data = JSON de player-prices: currentPrice, completedAuctions, liveAuctions."""
    d = data.get("data", {}) if isinstance(data, dict) else {}
    cur = (d.get("currentPrice") or {}).get("price")
    ventas = d.get("completedAuctions") or []
    bn = sorted(v["soldPrice"] for v in ventas if not v.get("isBid"))
    subs = sorted(a["buyNowPrice"] for a in d.get("liveAuctions") or [])
    rec = sorted((v for v in ventas if not v.get("isBid") and v.get("soldDate")), key=lambda v: v["soldDate"])[-15:]
    bn15 = sorted(v["soldPrice"] for v in rec)
    out = {"precio_actual": cur, "ventas_n": len(ventas), "ventas_buynow_n": len(bn)}
    if bn:
        med = bn[len(bn) // 2]
        out.update({
            "venta_mediana": med,
            "venta_mediana_15": bn15[len(bn15) // 2] if len(bn15) >= 5 else None,   # ultimas 15 ventas Buy Now
            "venta_min": bn[0],
            "venta_max": bn[-1],
            "venta_p10": bn[max(0, len(bn) // 10)],
            "venta_p25": bn[len(bn) // 4],                 # precio al que se compra de verdad con frecuencia (no el BIN suelto mas barato)
            "venta_p75": bn[(len(bn) * 3) // 4],
            # ganancia si compras al precio actual y vendes a la mediana, con el 5% de EA
            "ganancia_neta_a_mediana": (int(med * 0.95) - cur) if cur else None,
        })
    try:
        fechas = [_fecha(v["soldDate"]) for v in ventas if v.get("soldDate")]
        if fechas:
            horas = max((max(fechas) - min(fechas)).total_seconds() / 3600, 0.05)
            out["ventas_span_h"] = round(horas, 1)                 # cuanto tiempo cubren esas ventas
            out["ventas_por_hora"] = round(len(bn) / horas, 1)     # liquidez (Buy Now por hora)
            ahora = datetime.datetime.now(datetime.timezone.utc)
            out["ultima_venta_hace_min"] = int((ahora - max(fechas)).total_seconds() / 60)
    except Exception:
        pass
    if subs:
        out["subasta_buynow_min"] = subs[0]
        out["subastas_n"] = len(subs)
    return out


def bloqueado(status, texto):
    t = (texto or "").lower()
    return status in (403, 429, 503) or any(m in t[:3000] for m in MARCAS)


def leer(page, url):
    """Devuelve (detalle, estado). detalle=None => bloqueo: parar y no reintentar por 2 h."""
    r = None
    try:
        with page.expect_response(lambda x: "/api/fut/player-prices/" in x.url, timeout=25000) as info:
            r = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        resp = info.value
        status = resp.status
        if status in (403, 429, 503):
            return None, f"BLOQUEO status={status}"
        datos = resp.json()
    except Exception as e:
        status = r.status if r else 0
        try:
            texto = page.inner_text("body")
        except Exception:
            texto = ""
        if bloqueado(status, texto):
            return None, f"BLOQUEO status={status}"
        return {"url": url, "error": str(e)[:200]}, "ok"

    page.wait_for_timeout(1200)
    try:
        texto = page.inner_text("body")
    except Exception:
        texto = ""
    if bloqueado(status, texto):
        return None, f"BLOQUEO status={status}"

    det = {"url": url, "leido": time.strftime("%Y-%m-%dT%H:%M:%S")}
    det.update(resumen_api(datos))
    for etq, clave in (("Lowest", "rango_pagina_min"), ("Average", "rango_pagina_prom"), ("Highest", "rango_pagina_max")):
        mm = re.search(etq + r"\s*\n\s*([\d,]+)", texto)
        if mm:
            det[clave] = num(mm.group(1))
    return det, "ok"


def main():
    from playwright.sync_api import sync_playwright
    args = sys.argv[1:]
    if args[:1] == ["--archivo"]:
        urls = [l.strip() for l in open(args[1], encoding="utf-8-sig") if l.strip() and not l.startswith("#")]
    else:
        urls = args
    urls = urls[:MAX_CARTAS]
    if not urls:
        print(__doc__)
        return
    resultado = {"cartas": [], "estado": "ok"}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        for i, u in enumerate(urls):
            if i:
                time.sleep(PAUSA_S)
            det, est = leer(page, u)
            if det is None:
                resultado["estado"] = est + " - detenido, reintentar en 2 h"
                break
            resultado["cartas"].append(det)
            print(u.rstrip("/").split("/")[-1], det.get("precio_actual"), "mediana venta:", det.get("venta_mediana"))
        b.close()
    SALIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Guardado:", SALIDA, "| estado:", resultado["estado"])


if __name__ == "__main__":
    main()
