"""Confirma las candidatas del listado amplio en la pagina de cada carta (solo lectura).
Lo llama recolectar.py justo despues del analisis amplio, con la misma pagina del navegador.
Para cada candidata (precio <= precio_max, las de mayor margen primero, maximo max_cartas):
  lee el precio actual y las ~100 ventas reales y calcula la ganancia neta (tras el 5%) a la mediana de venta.
Salidas: candidatas_confirmadas.json y un bloque 'CONFIRMADAS' al final de resumen_corto.txt.
Reglas: 4 s entre paginas; si hay Cloudflare/403/429 devuelve el motivo y recolectar.py se detiene 2 h.
No compra, no vende, no pulsa nada. Opciones en config.ini, seccion [confirmar] (todas opcionales):
  max_cartas=30  precio_max=25000  pausa=4  ganancia_min=300  margen_min_pct=4  ventas_min=10"""
import datetime, json, os, time
from comun import BASE, cfg, telegram, guardar_json, cargar_json
import leer_cartas

MARCA = "CONFIRMADAS EN LA PÁGINA DE LA CARTA"


def M(x):
    return f"{x:,}".replace(",", ".")


def opciones():
    c = cfg()
    g = lambda k, d: c.get("confirmar", k, fallback=d).strip()
    return {"max": int(g("max_cartas", "30")), "precio_max": int(g("precio_max", "25000")),
            "pausa": float(g("pausa", "4")), "gan_min": int(g("ganancia_min", "300")),
            "pct_min": float(g("margen_min_pct", "4")), "ventas_min": int(g("ventas_min", "10")),
            "compra": g("compra_realista", "p25"), "recencia_min": int(g("recencia_min", "180")),
            "dedupe_h": float(g("dedupe_h", "6")), "max_avisos": int(g("max_avisos", "6"))}


def veredicto(c, det, O):
    """c = candidata del amplio; det = lectura de la pagina. Devuelve dict con ok y una linea de texto."""
    base = {"n": c["n"], "r": c["r"], "t": c["t"], "p": c["p"], "href": c["href"], "pc_lista": c["pc"]}
    if det.get("error") or not det.get("precio_actual") or not det.get("venta_mediana"):
        base.update({"ok": False, "linea": f"⚪ {c['n']} {c['r']}: sin datos en la página ({det.get('error', 'sin ventas')[:60]})"})
        return base
    pa = det["precio_actual"]
    med = min(det["venta_mediana"], det.get("venta_mediana_15") or det["venta_mediana"])   # si ya bajo, manda lo reciente
    # Comprar al BIN minimo es casi imposible (dura minutos). Se calcula con un precio de compra realista:
    # el percentil de las ventas reales (p10, p25 o p50 = mediana) o el BIN actual si es mayor.
    clave = {"p10": "venta_p10", "p25": "venta_p25", "p50": "venta_mediana"}.get(O["compra"], "venta_p25")
    real = max(pa, det.get(clave) or pa)
    gan = int(med * 0.95) - real
    pct = gan / real * 100
    gan_bin = int(med * 0.95) - pa
    notas = []
    if abs(pa - c["pc"]) / c["pc"] > 0.05:
        notas.append(f"el precio cambió de {M(c['pc'])} a {M(pa)}")
    poco = False
    if det.get("ventas_buynow_n", 0) < O["ventas_min"]:
        notas.append(f"solo {det['ventas_buynow_n']} ventas Buy Now"); poco = True
    if det.get("ventas_span_h", 0) > 24:
        notas.append(f"ventas de hace {det['ventas_span_h']:.0f} h (poca liquidez)"); poco = True
    if det.get("ultima_venta_hace_min", 0) > O["recencia_min"]:
        notas.append(f"última venta hace {det['ultima_venta_hace_min']} min"); poco = True
    ok = gan >= O["gan_min"] and pct >= O["pct_min"] and not poco
    vph = det.get("ventas_por_hora")
    linea = (f"{'✅' if ok else '❌'} {c['n']} {c['r']} ({c['t']}, {c['p']}): BIN {M(pa)} (difícil de pillar) · compra realista ~{M(real)} · venta típica {M(med)} "
             f"({M(det['venta_min'])}-{M(det['venta_max'])}, {det['ventas_buynow_n']} ventas"
             f"{f', ~{vph}/h' if vph is not None else ''}) → ganancia neta realista {M(gan)} ({pct:.0f}%); al BIN sería {M(gan_bin)}")
    if notas:
        linea += " · " + "; ".join(notas)
    base.update({"ok": ok, "pc_ahora": pa, "venta_mediana": med, "venta_min": det["venta_min"], "venta_max": det["venta_max"],
                 "ventas_buynow_n": det["ventas_buynow_n"], "ventas_por_hora": vph, "ganancia_neta": gan,
                 "ganancia_pct": round(pct, 1), "compra_realista": real, "ganancia_neta_bin": gan_bin, "notas": notas, "linea": linea})
    return base


def confirmar(page, enviar=True):
    """Devuelve None si todo bien, o el motivo del bloqueo (recolectar.py lo guarda y se detiene 2 h)."""
    O = opciones()
    ruta = os.path.join(BASE, "amplio_candidatas.json")
    if not os.path.exists(ruta):
        return None
    doc = cargar_json(ruta, {})
    try:
        if (datetime.datetime.now() - datetime.datetime.fromisoformat(doc["fecha"])).total_seconds() > 1800:
            print("Candidatas viejas (el analisis amplio no corrio): no confirmo"); return None
    except Exception:
        return None
    cand = doc.get("candidatas", [])
    lista = [c for c in cand if c.get("href") and c["pc"] <= O["precio_max"]]
    lista.sort(key=lambda c: -c["margen_neto_pct"])
    lista = lista[:O["max"]]
    out, motivo = [], None
    for i, c in enumerate(lista):
        if i:
            time.sleep(O["pausa"])
        det, est = leer_cartas.leer(page, c["href"])
        if det is None:
            motivo = f"bloqueo/Cloudflare al confirmar {c['n']} ({est})"
            break
        out.append(veredicto(c, det, O))
        print(("OK " if out[-1]["ok"] else "no ") + c["n"])
    ahora = datetime.datetime.now()
    guardar_json(os.path.join(BASE, "candidatas_confirmadas.json"),
                 {"fecha": ahora.isoformat(timespec="minutes"), "revisadas": len(out), "de_candidatas": len(cand),
                  "precio_max": O["precio_max"], "confirmadas": [x for x in out if x["ok"]], "descartadas": [x for x in out if not x["ok"]]}, indent=1)
    buenas = [x for x in out if x["ok"]]
    bloque = [f"{MARCA} ({ahora:%H:%M}; {len(out)} de {len(cand)} candidatas, precio ≤ {M(O['precio_max'])}):"]
    bloque += [x["linea"] for x in sorted(buenas, key=lambda x: -x["ganancia_pct"])]
    bloque += [x["linea"] for x in out if not x["ok"]]
    if not out:
        bloque.append("(ninguna candidata dentro del precio máximo)")
    try:
        r = os.path.join(BASE, "resumen_corto.txt")
        t = open(r, encoding="utf-8").read() if os.path.exists(r) else ""
        t = t.split(MARCA)[0].rstrip() + "\n"
        open(r, "w", encoding="utf-8").write(t + "\n".join(bloque) + "\n")
    except Exception as e:
        print("No pude añadir las confirmadas a resumen_corto.txt:", e)
    if enviar and buenas:
        try:
            import analizar
            if not analizar.hora_silencio():
                ruta_av = os.path.join(BASE, "confirmadas_avisadas.json")
                av = cargar_json(ruta_av, {})
                nuevas = []
                for x in sorted(buenas, key=lambda x: -x["ganancia_pct"]):
                    ult = av.get(x["href"])
                    if ult and (ahora - datetime.datetime.fromisoformat(ult)).total_seconds() < O["dedupe_h"] * 3600:
                        continue
                    nuevas.append(x)
                nuevas = nuevas[:O["max_avisos"]]
                if nuevas and telegram("✅ Confirmadas en la página de la carta (tú decides, yo no compro):\n" + "\n".join(x["linea"] for x in nuevas)):
                    for x in nuevas: av[x["href"]] = ahora.isoformat(timespec="minutes")
                    av = {k: v for k, v in av.items() if (ahora - datetime.datetime.fromisoformat(v)).total_seconds() < 48 * 3600}
                    guardar_json(ruta_av, av)
        except Exception as e:
            print("Aviso de confirmadas fallo:", e)
    return motivo
