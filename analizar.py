"""Etapa 3: analiza la carpeta de datos mas reciente y manda alertas a Telegram.
Uso:  python analizar.py [carpeta] [--sin-telegram]
Reglas editables en config.ini ([reglas]). No compra ni vende nada: solo avisa."""
import datetime, json, os, re, statistics, sys
from comun import BASE, cfg, telegram, guardar_json, cargar_json

POS = {"GK","LB","CB","RB","LWB","RWB","CDM","CM","CAM","LM","RM","LW","RW","ST","CF"}

def M(x):
    return f"{x:,}".replace(",", ".")

def precio(s):
    s = (s or "").strip().replace(",", "")
    m = re.fullmatch(r"\+?(\d+(?:\.\d+)?)([KkMm]?)", s)
    if not m: return None
    v = float(m.group(1)); u = m.group(2).upper()
    return int(v * (1000 if u == "K" else 1000000 if u == "M" else 1))

def leer(ruta):
    try: return open(ruta, encoding="utf-8").read()
    except Exception: return ""

def reglas():
    c = cfg()
    g = lambda k, d: c.get("reglas", k, fallback=d).strip()
    return {
        "fodder_ratio": float(g("fodder_ratio", "0.92")),
        "fodder_min_lecturas": int(g("fodder_min_lecturas", "4")),
        "cambio_pct": float(g("cambio_pct", "10")),
        "cambio_min_precio": int(g("cambio_min_precio", "5000")),
        "tl_ganancia_pct": float(g("tl_ganancia_pct", "10")),
        "amp_baja_min": float(g("amp_baja_min", "10")), "amp_baja_max": float(g("amp_baja_max", "20")),
        "amp_lecturas": int(g("amp_lecturas", "4")), "amp_min_precio": int(g("amp_min_precio", "2000")),
        "equipo": [x.strip().lower() for x in g("equipo", "salma,aitana").split(",") if x.strip()],
        "estancada_lecturas": int(g("estancada_lecturas", "6")),     # lecturas seguidas en la Transfer List sin venderse (~2 h c/u)
        "capital_pct": float(g("capital_pct", "40")),               # % del dinero total parado en la Transfer List que dispara el aviso
        "presupuesto": int(g("presupuesto", "1100000")),            # solo si no hay progreso.json
        "fuera_pct": float(g("fuera_pct", "10")),                   # tu precio listado vs mercado
        "amp_margen_min": float(g("amp_margen_min", "3")),          # margen neto minimo (tras 5%) para listar en candidatas
        "meta_monedas": int(g("meta_monedas", "5000000")),
        "meta_fecha": g("meta_fecha", "2027-01-15"),
        "dedupe_h": float(g("dedupe_h", "6")), "max_pines": int(g("max_pines", "6")),
        "cambio_max_precio": int(g("cambio_max_precio", "150000")),
        "fodder_media_min": int(g("fodder_media_min", "84")), "fodder_media_max": int(g("fodder_media_max", "90")),
        "fodder_min_cartas": int(g("fodder_min_cartas", "5")), "fodder_ref_horas": float(g("fodder_ref_horas", "36")),
        "estancada_dias": float(g("estancada_dias", "3")),
        "amp_max_candidatas": int(g("amp_max_candidatas", "120")),
        "ocioso_flips": int(g("ocioso_flips", "20")),
    }

def cargar_progreso(ahora):
    """progreso.json lo escribe la revision de Claude (monedas, ganancia_hoy, ganancia_7d). Si es viejo (>36 h) se ignora."""
    try:
        p = json.load(open(os.path.join(BASE, "progreso.json"), encoding="utf-8"))
        t = datetime.datetime.fromisoformat(p["fecha"]).replace(tzinfo=None)
        if (ahora - t).total_seconds() > 36 * 3600: return {}
        return p
    except Exception:
        return {}

def resumen_diario(ultimo, R, ahora):
    pr = cargar_progreso(ahora)
    ct = ultimo.get("capital_tl") or {}
    L = [f"📊 Resumen del día {ahora:%d/%m} (22:07)"]
    L.append(f"Transfer List: {ultimo.get('tl_cartas', 0)} cartas; {ct.get('cartas', 0)} con precio pagado: pagaste {M(ct.get('pagado', 0))}, mercado {M(ct.get('valor_mercado', 0))}, ganancia potencial {M(ct.get('ganancia_potencial', 0))} tras 5%.")
    if ultimo.get("estancadas"): L.append(f"⏳ Estancadas (≥{R['estancada_lecturas']} lecturas): {len(ultimo['estancadas'])}.")
    if pr.get("ganancia_hoy") is not None: L.append(f"Ganancia de hoy (tradeos de la Mesa, tras 5%): {M(pr['ganancia_hoy'])}.")
    else: L.append("Ganancia de hoy: sin dato (la actualiza la revisión de Claude).")
    if pr.get("monedas"):
        m = pr["monedas"]; meta = R["meta_monedas"]
        dias = max(1, (datetime.date.fromisoformat(R["meta_fecha"]) - ahora.date()).days)
        L.append(f"Meta {M(meta)}: llevas {M(m)} ({m / meta * 100:.0f}%). Faltan {dias} días: necesitas ~{M(max(0, meta - m) // dias)} por día.")
        L.append(f"Ritmo compuesto necesario: {((meta / m) ** (7 / dias) - 1) * 100:.0f}% por semana.")
        if pr.get("ganancia_7d") is not None:
            ritmo = pr["ganancia_7d"] / 7
            L.append(f"Tu ritmo de 7 días: ~{M(int(ritmo))} por día → a este ritmo llegarías a ~{M(int(m + ritmo * dias))} el {R['meta_fecha']}." + (" Vas a tiempo." if m + ritmo * dias >= meta else f" Te faltan ~{M(int((meta - m) / dias - ritmo))} por día más."))
    else:
        L.append("Meta 5M: sin dato de monedas (la actualiza la revisión de Claude).")
    return "\n".join(L)

def resumen_corto(ultimo, cand=None, ana=None):
    """Archivo corto para la revision de Claude: lo esencial sin abrir los archivos grandes."""
    L = [f"Lectura {ultimo.get('fecha')} · carpeta {ultimo.get('carpeta')} · club_sync {ultimo.get('club_sync')} · TL {ultimo.get('tl_cartas', 0)} cartas"]
    L.append(f"LECTURA_EPOCH: {ultimo.get('fecha_epoch')} · la edad la calcula quien lee (ahora menos este valor); si pasa de 3 h, no analizar y avisar")
    fr = ultimo.get("fodder_ref") or {}
    L.append("Fodder piso (3.ª más barata): " + ", ".join(f"{r}: {(v[2] if len(v) >= 3 else v[0])['pc']}" for r, v in sorted(ultimo.get("fodder", {}).items()) if v) + (" · ref: " + ", ".join(f"{r}: {d['cambio_pct']:+.1f}%" for r, d in sorted(fr.items())) if fr else " · ref: aún sin 4 lecturas"))
    fpd = {r: d for r, d in (ultimo.get("fodder_por_dia") or {}).items() if len(d) >= 3 and r in ("85", "86", "87")}
    if fpd: L.append("Fodder por día de la semana (media del piso): " + " | ".join(f"{r}: " + ", ".join(f"{k} {M(v)}" for k, v in d.items()) for r, d in fpd.items()))
    if ultimo.get("espacios_libres") is not None: L.append(f"Espacios libres en la Transfer List: {ultimo['espacios_libres']} de 100")
    L.append("ALERTAS DEL SCRIPT (citar tal cual):")
    L += [f"- {a}" for a in ultimo.get("alertas_script", [])[:25]] or ["- ninguna"]
    if ultimo.get("desaparecidas"): L.append("Desaparecidas de la TL: " + "; ".join(f"{d['cantidad']}× {d['n']} {d['r']}" for d in ultimo["desaparecidas"]))
    ct = ultimo.get("capital_tl")
    if ct: L.append(f"Capital en TL: {M(ct['pagado'])} en {ct['cartas']} cartas con precio pagado; ganancia potencial {M(ct['ganancia_potencial'])}.")
    if cand:
        L.append(f"Listado amplio: {cand.get('leidas', '?')} cartas leídas; candidatas {cand.get('candidatas_total', len(cand.get('candidatas', [])))}, de ellas {cand.get('candidatas_en_precio', '?')} dentro del precio máximo de confirmar (se muestran 40), de mayor a menor caída:")
        L += [f"- {c['n']} {c['r']} ({c['t']}, {c['p']}): {M(c['pc'])} vs mediana {M(c['mediana'])} (-{c['baja_pct']:.0f}%, margen neto {c['margen_neto_pct']:.0f}%)" for c in cand.get("candidatas", [])[:40]]
    if ultimo.get("tl_sobrepago"): L.append("Pagaste de más (≥8% sobre mercado actual): " + "; ".join(f"{d['n']} {d['r']}: pagado {M(d['pagado'])} vs mercado {M(d['mercado'])}" for d in ultimo["tl_sobrepago"]))
    if ana:
        L.append("Caída sostenida (4 lecturas bajando, no es trampa): " + ("; ".join(f"{d['n']} {d['r']} {M(d['pc'])} (-{d['caida_4_lecturas_pct']:.0f}%)" for d in ana["caida_sostenida_top15"][:8]) or "ninguna"))
        L.append("Rebote (bajó ≥15% y se estabiliza): " + ("; ".join(f"{d['n']} {d['r']} {M(d['pc'])} (mín {M(d['minimo'])})" for d in ana["rebote_top15"][:8]) or "ninguno"))
        L.append("Más volátiles hoy: " + ("; ".join(f"{d['n']} {d['r']} {M(d['pc'])} ({d['volatilidad_pct']}%)" for d in ana["volatilidad_top15"][:6]) or "sin datos"))
        if ana["precios_raros_fodder"]: L.append("Precios raros fodder: " + "; ".join(ana["precios_raros_fodder"]))
        hp = ana["hora_precio_fodder"]; L.append(f"Hora fodder: comprar {hp['mejor_hora_comprar']}, vender {hp['mejor_hora_vender']}")
        if ana["promos_nuevas_7d"]: L.append("Promos nuevas 7 d: " + "; ".join(f"{d['n']} {d['r']} {d['cambio_pct']:+.0f}%" for d in ana["promos_nuevas_7d"][:6]))
    return "\n".join(L)

# ---------- FUTWIZ fodder ----------
def parse_futwiz(texto, rating_por_defecto=None):
    """Devuelve {rating: [(nombre, pos, precioPC)]}. El segundo precio es PC."""
    L = [x.strip() for x in texto.split("\n")]
    res, rating = {}, rating_por_defecto
    for i, x in enumerate(L):
        # formato por media: "85 / CB / Guehi / stats... / Right / 2.5K / 3.0K"
        if re.fullmatch(r"\d\d", x) and i + 2 < len(L) and L[i+1] in POS:
            for j in range(i + 3, min(i + 45, len(L) - 2)):
                if L[j].lower() in ("right", "left"):
                    b = precio(L[j+2])
                    if b is not None: res.setdefault(int(x), []).append((L[i+2], L[i+1], b))
                    break
            continue
        # formato de la pagina general: "NN Rating" y luego Nombre / POS / precio / precio
        m = re.fullmatch(r"(\d\d) Rating", x)
        if m: rating = int(m.group(1)); continue
        if x in POS and i >= 1 and i + 2 < len(L) and rating:
            a, b = precio(L[i+1]), precio(L[i+2])
            if a is not None and b is not None and L[i-1] and L[i-1] not in POS:
                res.setdefault(rating, []).append((L[i-1], x, b))
    return res

# ---------- fut.gg: enlaces con nombre/precio ----------
def parse_links(ruta):
    cartas = {}
    for linea in leer(ruta).splitlines():
        p = [x.strip() for x in linea.split(" | ")]
        if len(p) < 3: continue
        h, t, alt = p[0], p[1], p[2]
        m = re.search(r"/players/(\d+)-[^/]+/([^/]+)/?", h)
        if not m: continue
        partes = [x.strip() for x in t.split("/")]
        a = [x.strip() for x in alt.split(" - ")]
        if len(a) < 2: continue
        pr = precio(partes[-1]) if len(partes) >= 3 else None
        cartas[m.group(2)] = {"n": a[0], "ovr": a[1], "tipo": " - ".join(a[2:]), "pos": partes[0], "pc": pr, "extinta": "EXTINCT" in t.upper(),
                              "href": ("https://www.fut.gg" + h) if h.startswith("/") else h}
    return cartas

# ---------- Transfer List ----------
def parse_tl(texto):
    L = [x.strip() for x in texto.split("\n") if x.strip()]
    out, i = [], 0
    try: i = L.index("Sale profit") + 2     # salta el resumen del encabezado
    except ValueError: pass
    bloque = []
    for x in L[i:]:
        if x == "Open in GG Club":
            c = {"n": bloque[0] if bloque else "?"}
            try:
                k = bloque.index("Paid")
                c["mercado"] = precio(bloque[k-1]); c["pagado"] = precio(bloque[k+1])
                c["ovr"] = bloque[1]
                j = bloque.index("Market profit"); c["ganancia"] = precio(bloque[j+1].replace("+", "")) if not bloque[j+1].startswith("-") else -(precio(bloque[j+1][1:]) or 0)
                c["listado"] = "Not listed" not in bloque
            except Exception: pass
            out.append(c); bloque = []
        else: bloque.append(x)
    return out

def objetivos():
    """Cartas para jugar que se vigilan: config.ini [objetivos] lista = nombre|media|tipo; ..."""
    txt = cfg().get("objetivos", "lista", fallback="dumornay|88|rare; hasegawa|89|rttk")
    out = []
    for x in txt.split(";"):
        p = [y.strip().lower() for y in x.split("|")]
        if len(p) == 3 and p[0]: out.append(tuple(p))
    return out

def hora_silencio():
    h = datetime.datetime.now().hour
    return 1 <= h < 8

def main(carpeta=None, enviar=True):
    datos = os.path.join(BASE, "datos")
    if not carpeta:
        carpeta = os.path.join(datos, sorted(os.listdir(datos))[-1])
    R = reglas()
    est_ruta = os.path.join(BASE, "estado.json")
    est = cargar_json(est_ruta, {})
    est.setdefault("fodder", {}); est.setdefault("cartas", {}); est.setdefault("avisado", {})
    if est.get("fodder_fuente") != "FUT.GG piso3":   # el historial anterior era de FUTWIZ: se reinicia para no mezclar fuentes
        est["fodder"] = {}; est["fodder_fuente"] = "FUT.GG piso3"
    ahora = datetime.datetime.now()
    alertas, info = [], []
    ultimo = {"fecha": ahora.isoformat(timespec="minutes"), "plataforma": "PC", "fuente": "script local (FUT.GG)", "carpeta": os.path.basename(carpeta), "fodder": {}, "cartas": [], "transfer_list": []}

    # 1) Fodder (FUT.GG, PC, solo Rare/Common). FUTWIZ ya no se usa.
    fw = {}
    for f in os.listdir(carpeta):
        m = re.fullmatch(r"fg(\d\d)(?:_\d+)?\.links\.txt", f)
        if not m: continue
        for c in parse_links(os.path.join(carpeta, f)).values():
            if c["tipo"] in ("Rare", "Common") and c["pc"] and not c["extinta"] and c["pc"] < 15000000:
                fw.setdefault(int(m.group(1)), []).append((c["n"], c["pos"], c["pc"]))
    for r, v in sorted(fw.items()):
        if not (R["fodder_media_min"] <= r <= R["fodder_media_max"]) or len(v) < R["fodder_min_cartas"]:
            info.append(f"{r}: sin dato fiable ({len(v)} cartas)"); continue
        v = sorted(v, key=lambda x: x[2])
        minimo = v[2]                                  # piso con profundidad: 3.a carta mas barata
        hist = est["fodder"].setdefault(str(r), [])
        lim = (ahora - datetime.timedelta(hours=R["fodder_ref_horas"])).isoformat(timespec="minutes")
        prev = [h["p"] for h in hist if h["t"] >= lim][-12:]      # no se compara con lecturas de hace dias
        rara = False
        if len(prev) >= R["fodder_min_lecturas"]:
            ref = int(statistics.median(prev))
            rara = not (0.5 * ref <= minimo[2] <= 1.5 * ref)
            ultimo.setdefault("fodder_ref", {})[str(r)] = {"ref": ref, "min": minimo[2], "lecturas": len(prev), "cambio_pct": round((minimo[2] / ref - 1) * 100, 1), "rara": rara}
            if not rara and minimo[2] <= R["fodder_ratio"] * ref:
                alertas.append(f"🟢 FODDER BAJÓ {r}: {minimo[0]} ({minimo[1]}) a {M(minimo[2])} (ref {M(ref)}, {(minimo[2]/ref-1)*100:.0f}%). Fuente FUT.GG (PC): confirma en el mercado antes de comprar.")
        if rara:
            info.append(f"{r}: lectura rara {minimo[2]}, no se guarda")
        else:
            hist.append({"t": ahora.isoformat(timespec="minutes"), "p": minimo[2]})
            info.append(f"{r}: {minimo[2]}")
            fd = est.setdefault("fodder_dia", {}).setdefault(str(r), {}).setdefault(str(ahora.weekday()), [])   # piso por dia de la semana
            fd.append(minimo[2]); del fd[:-60]
        est["fodder"][str(r)] = hist[-40:]
        ultimo["fodder"][str(r)] = [{"n": x[0], "p": x[1], "pc": x[2]} for x in v[:5]]

    DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    ultimo["fodder_por_dia"] = {r: {DIAS[int(d)]: int(sum(v) / len(v)) for d, v in sorted(dd.items()) if v} for r, dd in sorted(est.get("fodder_dia", {}).items())}

    # 2) Cambios de precio en paginas calientes
    vistos = {}
    for f in sorted(os.listdir(carpeta)):
        if f.endswith(".links.txt") and not f.startswith(("club", "fodder", "futwiz", "fw", "fg", "amp", "gal")):
            pagina = f[:-len(".links.txt")]
            m = re.fullmatch(r"TOTW(\d+)", pagina)
            grupo = f"TOTW {m.group(1)}" if m else re.sub(r"(?<!^)([A-Z])", r" \1", pagina)
            tipo = "IF" if m else ("Popular" if pagina == "populares" else "Promo")
            for k, c in parse_links(os.path.join(carpeta, f)).items():
                if c["pc"]:
                    vistos[k] = c
                    try: media = int(c["ovr"])
                    except ValueError: media = 0
                    ultimo["cartas"].append({"k": f"fb-{pagina}-{k}", "n": c["n"], "p": c["pos"], "r": media, "t": tipo, "g": grupo, "pc": c["pc"], "version": c["tipo"]})
    for k, c in vistos.items():
        ant = est["cartas"].get(k)
        if ant and ant["pc"] >= R["cambio_min_precio"] and c["pc"] <= R["cambio_max_precio"]:
            ch = (c["pc"] / ant["pc"] - 1) * 100
            if abs(ch) >= R["cambio_pct"]:
                alertas.append(f"📌 {c['n']} {c['ovr']} ({c['pos']}, {c['tipo']}): {M(ant['pc'])} → {M(c['pc'])} ({ch:+.0f}%)")
        est["cartas"][k] = {"pc": c["pc"], "n": c["n"], "t": ahora.isoformat(timespec="minutes")}

    # 3) Transfer List
    tl = parse_tl(leer(os.path.join(carpeta, "club_transferlist.txt")))
    grupos = {}
    for c in tl:
        if c.get("pagado") and c.get("ganancia") is not None and not any(e in c["n"].lower() for e in R["equipo"]):
            grupos.setdefault((c["n"], c.get("ovr", ""), c["pagado"], c["mercado"], c["ganancia"]), 0)
            grupos[(c["n"], c.get("ovr", ""), c["pagado"], c["mercado"], c["ganancia"])] += 1
    for (n, ovr, pag, mer, gan), cant in grupos.items():
        pct = gan / pag * 100
        if pct >= R["tl_ganancia_pct"]:
            x = f"{cant}× " if cant > 1 else ""
            alertas.append(f"💰 {x}{n} {ovr}: pagaste {M(pag)}, mercado {M(mer)}, ganancia {M(gan)} c/u ({pct:.0f}%) tras 5%.")
    tl_resumen = f"TL: {len(tl)} cartas" if tl else "TL: sin leer"
    ultimo["transfer_list"] = [{"n": c["n"], "r": c.get("ovr"), "mercado": c.get("mercado"), "pagado": c.get("pagado"), "ganancia_tras_5pct": c.get("ganancia")} for c in tl]
    try:
        import exportar
        extra = exportar.generar(carpeta, parse_links, parse_futwiz, precio, leer)
        raw = extra.pop("_raw", "")
        open(os.path.join(BASE, "raw.txt"), "w", encoding="utf-8").write(raw)
        ultimo.update(extra)
        ultimo["raw_lineas"] = raw.count("\n")
    except Exception as e:
        ultimo["error_exportar"] = str(e)
    # Cartas que desaparecieron de la Transfer List desde la lectura anterior (vendidas o movidas a la plantilla)
    tlh = [c for c in ultimo.get("transfer_list", []) if c.get("href")]
    if ultimo.get("tl_leida"):
        actual = {c["href"]: c for c in tlh}
        idas = {}
        for h, c in est.get("tl_prev", {}).items():
            if h not in actual:
                k = (c.get("n"), c.get("r"), c.get("publicado"), c.get("mercado"))
                idas[k] = idas.get(k, 0) + 1
        ultimo["desaparecidas"] = [{"n": k[0], "r": k[1], "publicado": k[2], "mercado": k[3], "cantidad": q} for k, q in idas.items()]
        for (n, r, pub, mer), q in idas.items():
            x = f"{q}× " if q > 1 else ""
            p = f"estaba publicada a {M(pub)}" if pub else (f"mercado ~{M(mer)}" if mer else "sin precio")
            alertas.append(f"📤 {x}{n} {r or ''} ya no está en tu Transfer List ({p}). ¿Vendida o la pasaste a la plantilla? Si la vendiste, dile a Claude a cuánto.")
        est["tl_prev"] = {h: {"n": c.get("n"), "r": c.get("r"), "publicado": c.get("publicado"), "mercado": c.get("mercado")} for h, c in actual.items()}
    ultimo["tl_cartas"] = len(ultimo.get("transfer_list", []))
    if ultimo.get("tl_leida") and ultimo["tl_cartas"] >= 85:
        alertas.append(f"📦 Tu Transfer List tiene {ultimo['tl_cartas']} de 100 cartas: libera espacio antes de comprar más.")
    # --- Funciones del 12 nov: cartas estancadas, capital inmovilizado, precio fuera de mercado ---
    if ultimo.get("tl_leida"):
        t_ep = ahora.timestamp()
        edad_prev = est.get("tl_edad", {})
        edad = {}
        flips, estanc = [], {}
        for c in tlh:
            if any(e in (c.get("n") or "").lower() for e in R["equipo"]): continue
            if c.get("pagado") is None and c.get("publicado") is None: continue   # empaquetadas/sin publicar: no son flips
            h = c["href"]; p = edad_prev.get(h, {"n": 0, "t": 0})
            n, t = (p["n"] + 1, t_ep) if t_ep - p["t"] >= 5400 else (p["n"], p["t"])   # una lectura nueva = al menos 90 min despues
            desde = p.get("desde", t_ep)               # primera vez que se vio en la Transfer List
            edad[h] = {"n": n, "t": t, "desde": desde}
            dias = int((t_ep - desde) // 86400)
            if c.get("pagado"): flips.append(c)
            L = R["estancada_lecturas"]
            if (n >= L and (n - L) % 3 == 0) or (dias >= R["estancada_dias"] and n % 3 == 0):
                k = (c.get("n"), c.get("r"), c.get("publicado"), c.get("mercado"), n, dias)
                estanc[k] = estanc.get(k, 0) + 1
        est["tl_edad"] = edad
        ultimo["estancadas"] = [{"n": k[0], "r": k[1], "publicado": k[2], "mercado": k[3], "lecturas": k[4], "dias": k[5], "cantidad": q} for k, q in estanc.items()]
        for (n, r, pub, mer, lect, dias), q in estanc.items():
            x = f"{q}× " if q > 1 else ""
            tu = f", tú la tienes a {M(pub)}" if pub else ""
            regla = " Regla de 3 días: véndela a mercado y recicla." if dias >= R["estancada_dias"] else " Considera relistarla más barata."
            alertas.append(f"⏳ {x}{n} {r or ''}: lleva {dias} día(s) y {lect} lecturas en tu Transfer List sin venderse. Mercado {M(mer) if mer else '?'}{tu}.{regla}")
        pagado = sum(c["pagado"] for c in flips)
        ultimo["capital_tl"] = {"cartas": len(flips), "pagado": pagado, "valor_mercado": sum(c.get("mercado") or 0 for c in flips), "ganancia_potencial": sum(c.get("ganancia_mercado") or 0 for c in flips)}
        libres = max(0, 100 - ultimo["tl_cartas"]); ultimo["espacios_libres"] = libres
        if len(flips) < R["ocioso_flips"] and any(a.startswith("🟢 FODDER BAJÓ") for a in alertas):
            alertas.append(f"🪙 Espacios vacíos: solo {len(flips)} flips en tu Transfer List y hay fodder barato. Caben {libres} cartas más (máximo ~10 copias por carta y precios de venta escalonados).")
        ultimo["tl_sobrepago"] = [{"n": c.get("n"), "r": c.get("r"), "pagado": c["pagado"], "mercado": c["mercado"]} for c in flips if c.get("mercado") and c["pagado"] >= c["mercado"] * 1.08]
        pr = cargar_progreso(ahora)
        if pr.get("monedas") is not None:
            total = pr["monedas"] + pagado; base = f"de tus ~{M(total)} (monedas + cartas pagadas)"; libre = f" Te quedan {M(pr['monedas'])} libres para flips."
        else:
            total = R["presupuesto"]; base = f"de tu presupuesto de {M(total)}"; libre = ""
        if flips and total and pagado / total * 100 >= R["capital_pct"]:
            alertas.append(f"🧊 Capital inmovilizado: {M(pagado)} en {len(flips)} cartas de tu Transfer List ({pagado / total * 100:.0f}% {base}).{libre}")
        # precio fuera de mercado (solo si la TL muestra tu precio listado)
        comp = [c for c in tlh if c.get("publicado") and c.get("mercado") and not any(e in (c.get("n") or "").lower() for e in R["equipo"])]
        ultimo["tl_publicado_visible"] = len(comp)
        fuera = {}
        for c in comp:
            d = (c["publicado"] / c["mercado"] - 1) * 100
            if abs(d) >= R["fuera_pct"]:
                k = (c.get("n"), c.get("r"), c["publicado"], c["mercado"], round(d)); fuera[k] = fuera.get(k, 0) + 1
        for (n, r, pub, mer, d), q in fuera.items():
            x = f"{q}× " if q > 1 else ""
            alertas.append((f"📈 {x}{n} {r or ''}: la tienes a {M(pub)} y el mercado está en {M(mer)} ({d:+d}%): difícil que se venda, bájala." if d > 0 else f"📉 {x}{n} {r or ''}: la tienes a {M(pub)} y el mercado está en {M(mer)} ({d:+d}%): estás regalando monedas, súbela."))
    ultimo["alertas_script"] = list(alertas)   # la tarea de Claude las cita tal cual, sin recalcular
    ultimo["fecha_epoch"] = int(ahora.timestamp())
    ultimo["resumen_diario"] = resumen_diario(ultimo, R, ahora)
    guardar_json(os.path.join(BASE, "ultimo.json"), ultimo, indent=1)
    try: open(os.path.join(BASE, "resumen_corto.txt"), "w", encoding="utf-8").write(resumen_corto(ultimo))
    except Exception as e: print("resumen_corto fallo:", e)
    mandar_resumen = ahora.hour >= 22 and est.get("resumen_fecha") != str(ahora.date())   # una vez al dia, aunque la lectura de las 22:07 se atrase
    if mandar_resumen: est["resumen_fecha"] = str(ahora.date())

    # evitar repetir la misma alerta (clave estable: el fodder no depende del nombre de la carta)
    def clave(a):
        m = re.match(r"🟢 FODDER BAJÓ (\d+): .*? a ([\d.]+) ", a)
        return f"fodder|{m.group(1)}|{m.group(2)}" if m else a
    orden = ("📤", "📦", "⏳", "🧊", "📈", "📉", "💰", "🟢", "🪙")     # lo tuyo primero; los 📌 al final
    alertas.sort(key=lambda a: next((i for i, p in enumerate(orden) if a.startswith(p)), len(orden)))
    nuevas = []
    for a in alertas:
        ult = est["avisado"].get(clave(a))
        if ult and (ahora - datetime.datetime.fromisoformat(ult)).total_seconds() < R["dedupe_h"] * 3600: continue
        nuevas.append(a)
    a_enviar = [a for a in nuevas if not a.startswith("📌")] + [a for a in nuevas if a.startswith("📌")][:R["max_pines"]]

    resumen = f"{ahora:%H:%M} · {tl_resumen} · fodder: " + (", ".join(info) if info else "sin datos") + f" · {len(vistos)} cartas vigiladas"
    print(resumen)
    for a in nuevas: print(a)
    enviado = False
    if enviar and not hora_silencio():
        if a_enviar: enviado = telegram("\n".join(a_enviar) + f"\n\n{resumen}")
        elif ahora.hour in (10, 16): telegram("✅ Sin alertas. " + resumen)
        if mandar_resumen: telegram(ultimo["resumen_diario"])
    if enviado:                                    # solo se marca lo que Telegram acepto
        for a in a_enviar: est["avisado"][clave(a)] = ahora.isoformat(timespec="minutes")
    est["avisado"] = {k: v for k, v in est["avisado"].items() if (ahora - datetime.datetime.fromisoformat(v)).total_seconds() < 24 * 3600}
    guardar_json(est_ruta, est, indent=1)
    return nuevas

def analisis_amplio(hist, ahora, est):
    """Ideas 17-23: rangos de precio, volatilidad, caida sostenida, rebote, precios raros entre medias,
    mejor hora y promos nuevas. Solo lectura de amplio.json; escribe amplio_analisis.json."""
    out = {"fecha": ahora.isoformat(timespec="minutes")}
    equipo = reglas()["equipo"]
    vol, sost, reb = [], [], []
    for k, h in hist.items():
        s = h["h"]; pc = s[-1] if s else 0
        if len(s) < 4 or pc < 2000 or any(e in h["n"].lower() for e in equipo): continue
        info = {"n": h["n"], "r": h["r"], "t": h["t"], "p": h["p"], "pc": pc}
        med = statistics.median(s)
        vol.append((statistics.pstdev(s) / med * 100, dict(info, volatilidad_pct=round(statistics.pstdev(s) / med * 100, 1), mediana=int(med))))
        u = s[-4:]
        if u[0] > u[1] > u[2] > u[3]:
            tot = (1 - u[3] / u[0]) * 100
            if 5 <= tot < 20: sost.append((tot, dict(info, caida_4_lecturas_pct=round(tot, 1))))
        mn = min(s); i = len(s) - 1 - s[::-1].index(mn)
        if len(s) >= 6 and max(s[:i + 1]) >= mn * 1.15 and i <= len(s) - 3 and abs(pc / s[-2] - 1) <= 0.03 and pc <= mn * 1.08:
            reb.append((max(s[:i + 1]) / mn, dict(info, minimo=mn, maximo_previo=max(s[:i + 1]), lecturas_desde_minimo=len(s) - 1 - i)))
    vol.sort(key=lambda x: -x[0]); sost.sort(key=lambda x: -x[0]); reb.sort(key=lambda x: -x[0])
    out["volatilidad_top15"] = [d for _, d in vol[:15]]
    out["caida_sostenida_top15"] = [d for _, d in sost[:15]]
    out["rebote_top15"] = [d for _, d in reb[:15]]
    # 17: rangos de precio (cuantas candidatas y cuanta volatilidad media por rango)
    bandas = [(2000, 5000), (5000, 10000), (10000, 25000), (25000, 50000), (50000, 150000)]
    rg = []
    for lo, hi in bandas:
        v = [x for x in vol if lo <= x[1]["pc"] < hi]
        if v: rg.append({"rango": f"{M(lo)}-{M(hi)}", "cartas": len(v), "volatilidad_media_pct": round(sum(x[0] for x in v) / len(v), 1)})
    out["por_rango_precio"] = rg
    # 21: precios raros entre medias consecutivas (solo Rare/Common 80-90): una media mayor mas barata que la menor
    med_r = {}
    for h in hist.values():
        if h["h"] and str(h["r"]).isdigit() and 80 <= int(h["r"]) <= 90 and h["t"].strip().lower() in ("rare", "common"):
            med_r.setdefault(int(h["r"]), []).append(h["h"][-1])
    med_r = {r: statistics.median(v) for r, v in med_r.items() if len(v) >= 5}
    out["mediana_fodder_por_media"] = {str(r): int(v) for r, v in sorted(med_r.items())}
    out["precios_raros_fodder"] = [f"{r+1} ({M(int(med_r[r+1]))}) más barata que {r} ({M(int(med_r[r]))})" for r in sorted(med_r) if r + 1 in med_r and med_r[r + 1] < med_r[r] * 0.97]
    # 22: mejor hora del dia (indice de precio fodder vs su mediana; bajo = hora de comprar, alto = hora de vender)
    idx = []
    for h in hist.values():
        if len(h["h"]) >= 4 and h["t"].strip().lower() in ("rare", "common") and h["h"][-1] > 0:
            idx.append(h["h"][-1] / statistics.median(h["h"]))
    hi_est = est.setdefault("hora_idx", {})
    if len(idx) >= 50:
        hi_est.setdefault(str(ahora.hour), []).append(round(statistics.median(idx), 4))
        hi_est[str(ahora.hour)] = hi_est[str(ahora.hour)][-30:]
    prom = {int(hh): sum(v) / len(v) for hh, v in hi_est.items() if len(v) >= 3}
    out["hora_precio_fodder"] = {"lecturas_por_hora": {hh: len(v) for hh, v in sorted(hi_est.items(), key=lambda x: int(x[0]))},
        "mejor_hora_comprar": (min(prom, key=prom.get) if len(prom) >= 4 else "sin datos aún (necesita 3 lecturas en ≥4 horas distintas)"),
        "mejor_hora_vender": (max(prom, key=prom.get) if len(prom) >= 4 else "sin datos aún")}
    # 23: cartas de promo nuevas (aparecieron en el listado despues del arranque) y como van desde su primera lectura
    nuevas = []
    for k, h in hist.items():
        v = h.get("v")
        if v and h["t"].strip().lower() not in ("rare", "common") and len(h["h"]) >= 2 and (ahora - datetime.datetime.fromisoformat(v)).days <= 7:
            nuevas.append({"n": h["n"], "r": h["r"], "t": h["t"], "p": h["p"], "visto": v[:10], "primer_precio": h["h"][0], "pc": h["h"][-1], "cambio_pct": round((h["h"][-1] / h["h"][0] - 1) * 100, 1)})
    nuevas.sort(key=lambda d: d["cambio_pct"])
    out["promos_nuevas_7d"] = nuevas[:20]
    guardar_json(os.path.join(BASE, "amplio_analisis.json"), out, indent=1)
    return out

def amplio(carpeta, enviar=True):
    """Listado amplio (paginas amp*): historial propio en amplio.json y alertas de caida moderada. No toca la Mesa."""
    R = reglas()
    ruta = os.path.join(BASE, "amplio.json")
    hist = cargar_json(ruta, {})
    ahora = datetime.datetime.now()
    ya_habia = len(hist) > 500
    leidas = 0; alertas = []; candidatas = []; trampas = []
    for f in sorted(os.listdir(carpeta)):
        if not (f.startswith("amp") and f.endswith(".links.txt")): continue
        for k, c in parse_links(os.path.join(carpeta, f)).items():
            if not c["pc"] or c["extinta"] or c["pc"] >= 15000000: continue
            leidas += 1
            if k not in hist and ya_habia: hist[k] = {"n": c["n"], "r": c["ovr"], "t": c["tipo"], "p": c["pos"], "h": [], "v": ahora.isoformat(timespec="minutes")}
            h = hist.setdefault(k, {"n": c["n"], "r": c["ovr"], "t": c["tipo"], "p": c["pos"], "h": []})
            prev = [x for x in h["h"]][-12:]
            if len(prev) >= R["amp_lecturas"] and c["pc"] >= R["amp_min_precio"]:
                med = statistics.median(prev)
                baja = (1 - c["pc"] / med) * 100
                if not any(e in c["n"].lower() for e in R["equipo"]):
                    margen = (med * 0.95 / c["pc"] - 1) * 100     # margen neto si vuelve a la mediana, tras el 5%
                    d = {"n": c["n"], "r": c["ovr"], "t": c["tipo"], "p": c["pos"], "pc": c["pc"], "mediana": int(med), "baja_pct": round(baja, 1), "margen_neto_pct": round(margen, 1), "href": c.get("href", "")}
                    if R["amp_baja_min"] <= baja < R["amp_baja_max"] and margen >= R["amp_margen_min"]:
                        if c["pc"] <= R["cambio_max_precio"]:      # a Telegram solo lo que esta en tu rango de precio
                            alertas.append((baja, f"🔎 {c['n']} {c['ovr']} ({c['pos']}, {c['tipo']}): {M(c['pc'])} vs mediana {M(int(med))} (-{baja:.0f}%, margen neto ~{margen:.0f}%)"))
                        candidatas.append(d)
                    elif baja >= R["amp_baja_max"]: trampas.append(d)   # caida >20%: segun tus datos suele ser trampa; sirven de contraejemplo
            h["h"] = (prev + [c["pc"]])[-12:]
    candidatas.sort(key=lambda d: -d["baja_pct"]); trampas.sort(key=lambda d: -d["baja_pct"])
    # mas opciones: primero se guardan TODAS las que caben en el precio maximo de confirmar; el resto hasta completar el cupo
    pmax = int(cfg().get("confirmar", "precio_max", fallback="25000"))
    total_cand = len(candidatas); baratas = [d for d in candidatas if d["pc"] <= pmax]
    candidatas = sorted(baratas + [d for d in candidatas if d["pc"] > pmax][:max(0, R["amp_max_candidatas"] - len(baratas))], key=lambda d: -d["baja_pct"])
    cand = {"fecha": ahora.isoformat(timespec="minutes"), "leidas": leidas, "candidatas_total": total_cand, "candidatas_en_precio": len(baratas), "candidatas": candidatas, "ejemplos_trampa_mayor_20pct": trampas[:5], "nota": "Candidatas: caida 10-20% bajo la mediana de las ultimas lecturas y margen neto >= amp_margen_min. Los >20% son contraejemplos (regla de trampa)."}
    guardar_json(os.path.join(BASE, "amplio_candidatas.json"), cand, indent=1)
    guardar_json(ruta, hist)
    # Cartas que quieres para JUGAR (config [objetivos]): aviso cuando la caida frena
    # (el minimo quedo al menos 2 lecturas atras y antes habia bajado 5% o mas)
    est_ruta = os.path.join(BASE, "estado.json")
    est = cargar_json(est_ruta, {})
    try: ana = analisis_amplio(hist, ahora, est)
    except Exception as e: ana = None; print("analisis_amplio fallo:", e)
    ob_est = est.setdefault("objetivos", {})
    obj_alertas = []
    for item in objetivos():
        nombre, media, tipo = item
        for k, h in hist.items():
            if nombre in h["n"].lower() and str(h["r"]) == media and tipo in h["t"].lower():
                serie = ob_est.setdefault(k, {"n": f'{h["n"]} {h["r"]} ({h["t"]})', "h": [], "avisado": None})
                if h["h"] and (not serie["h"] or serie["h"][-1] != [ahora.isoformat(timespec="minutes"), h["h"][-1]]):
                    serie["h"] = (serie["h"] + [[ahora.isoformat(timespec="minutes"), h["h"][-1]]])[-40:]
                pr = [x[1] for x in serie["h"]]
                if len(pr) >= 4:
                    m = min(pr); i = len(pr) - 1 - pr[::-1].index(m)
                    if i <= len(pr) - 3 and max(pr[:i+1]) >= m * 1.05 and serie.get("avisado") != m:
                        serie["avisado"] = m
                        obj_alertas.append(f"🎯 {serie['n']}: la caída frenó. Mínimo {M(m)}, ahora {M(pr[-1])} ({len(pr)-1-i} lecturas sin nuevo mínimo). Es la carta que quieres para jugar: confirma en el juego.")
    av = est.setdefault("avisado", {})
    nuevas = []
    for baja, a in sorted(alertas, reverse=True):
        ult = av.get(a)
        if ult and (ahora - datetime.datetime.fromisoformat(ult)).total_seconds() < R["dedupe_h"] * 3600: continue
        nuevas.append(a)
    nuevas = nuevas[:10]
    print(f"Amplio: {leidas} cartas leidas, {len(hist)} en historial, {len(candidatas)} candidatas, {len(nuevas)} alertas nuevas")
    try:   # el resumen corto de la revision incluye las candidatas
        u = json.load(open(os.path.join(BASE, "ultimo.json"), encoding="utf-8"))
        open(os.path.join(BASE, "resumen_corto.txt"), "w", encoding="utf-8").write(resumen_corto(u, cand, ana))
    except Exception as e: print("resumen_corto (amplio) fallo:", e)
    if enviar and obj_alertas and not hora_silencio():
        telegram("\n".join(obj_alertas))
    for a in obj_alertas: print(a)
    if enviar and nuevas and not hora_silencio():
        if telegram("Posibles oportunidades (listado amplio). Solo lectura del script: confirma en FUT.GG y revisa si es meta antes de comprar.\n" + "\n".join(nuevas)):
            for a in nuevas: av[a] = ahora.isoformat(timespec="minutes")
    guardar_json(est_ruta, est, indent=1)
    return nuevas

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else None, enviar="--sin-telegram" not in sys.argv)
