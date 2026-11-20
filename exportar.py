"""Genera raw.txt (formato de snap.py) y los datos de la Transfer List a partir de la carpeta de datos.
Lo usa analizar.py. La tarea de Claude lee raw.txt y ultimo.json en vez de abrir paginas."""
import os, re

def limpio(s):
    return str(s).replace("|", " ").replace("\n", " ").strip()

def generar(carpeta, parse_links, parse_futwiz, precio, leer):
    out = {}
    archivos = sorted(os.listdir(carpeta))

    # ---------- Fodder: FUT.GG Rare/Common (fg84, fg84_2, ...); respaldo FUTWIZ ----------
    fg = {}
    for f in archivos:
        m = re.fullmatch(r"fg(\d\d)(?:_\d+)?\.links\.txt", f)
        if not m: continue
        r = int(m.group(1))
        for c in parse_links(os.path.join(carpeta, f)).values():
            if c["tipo"] in ("Rare", "Common") and c["pc"] and not c["extinta"] and c["pc"] < 15000000:
                fg.setdefault(r, []).append((c["n"], c["pos"], c["pc"]))
    fw = {}
    for f in archivos:
        m = re.fullmatch(r"fw(\d\d)\.txt", f)
        if m:
            for r, v in parse_futwiz(leer(os.path.join(carpeta, f)), int(m.group(1))).items():
                fw.setdefault(r, []).extend(v)
    fodder, fuente_fodder = {}, {}
    for r in range(83, 92):
        base = sorted(set(fg.get(r, [])), key=lambda x: x[2])
        if len(base) >= 5: fodder[r] = base[:10]; fuente_fodder[r] = "FUT.GG"
        elif fw.get(r): fodder[r] = sorted(set(fw[r]), key=lambda x: x[2])[:10]; fuente_fodder[r] = "FUTWIZ (respaldo)"
        elif base: fodder[r] = base[:10]; fuente_fodder[r] = "FUT.GG (pocas)"
    out["fodder_fuente"] = {str(k): v for k, v in fuente_fodder.items()}

    # ---------- raw.txt ----------
    L = []
    for f in archivos:
        m = re.fullmatch(r"((?:TOTW\d+)|(?:UltimateScream\d*)|(?:FutureStars\d*)|(?:RoadToTheKnockout\d*))\.links\.txt", f)
        if not m: continue
        pagina = m.group(1)
        cartas = [c for c in parse_links(os.path.join(carpeta, f)).values() if c["pc"]]
        if not cartas: continue
        L.append(f"#FB {pagina} {'IF' if pagina.startswith('TOTW') else 'Promo'}")
        for c in cartas:
            try: media = int(c["ovr"])
            except ValueError: continue
            L.append(f"{limpio(c['n'])}|{c['pos']}|{media}|0|{c['pc']}")
    if fodder:
        L.append("#FW")
        for r in sorted(fodder):
            for n, p, pc in fodder[r]: L.append(f"{r}|{limpio(n)}|{p}|{pc}")
    pop = os.path.join(carpeta, "populares.links.txt")
    if os.path.exists(pop):
        cartas = [c for c in parse_links(pop).values() if c["pc"]]
        if cartas:
            L.append("#POP")
            for c in cartas:
                try: media = int(c["ovr"])
                except ValueError: continue
                L.append(f"{limpio(c['n'])}|{media}|{c['pos']}|0|{c['pc']}")
    out["_raw"] = "\n".join(L) + "\n"

    # ---------- Transfer List con href y precio publicado ----------
    texto = leer(os.path.join(carpeta, "club_transferlist.txt"))
    enlaces = [l.split(" | ")[0].strip() for l in leer(os.path.join(carpeta, "club_transferlist.links.txt")).splitlines()
               if re.search(r"/gg-club/[^/]+/players/\d", l.split(" | ")[0])]
    m = re.search(r"Last synced ([^\n]+)", texto)
    out["club_sync"] = m.group(1).strip() if m else None
    out["tl_leida"] = "Every card in the transfer list" in texto
    T = [x.strip() for x in texto.split("\n") if x.strip()]
    tl, bloque = [], []
    try: i = T.index("Sale profit") + 2
    except ValueError: i = len(T)
    for x in T[i:]:
        if x != "Open in GG Club":
            bloque.append(x); continue
        c = {"n": bloque[0] if bloque else "?", "r": bloque[1] if len(bloque) > 1 else None, "p": bloque[2] if len(bloque) > 2 else None}
        try:
            k = bloque.index("Paid")
            c["mercado"] = precio(bloque[k-1]); c["pagado"] = precio(bloque[k+1])
            c["pagado_texto"] = bloque[k+1]
            j = bloque.index("Listing"); lt = bloque[j+1]
            c["estado"] = lt; c["publicado"] = precio(lt)
            q = bloque.index("Market profit"); g = bloque[q+1]
            c["ganancia_mercado"] = -(precio(g[1:]) or 0) if g.startswith("-") else precio(g.replace("+", ""))
        except Exception: pass
        c["href"] = enlaces[len(tl)] if len(tl) < len(enlaces) else None
        tl.append(c); bloque = []
    out["transfer_list"] = tl

    # ---------- Jugadores del club (3 paginas): solo cartas transferibles con precio de mercado ----------
    club, vistos_h, paginas = [], set(), 0
    for f in archivos:
        if not re.fullmatch(r"club_players\d+\.links\.txt", f): continue
        paginas += 1
        mejor = {}
        for l in leer(os.path.join(carpeta, f)).splitlines():
            p = [x.strip() for x in l.split(" | ")]
            if len(p) < 2 or not re.search(r"/gg-club/[^/]+/players/\d", p[0]): continue
            if len(p[1]) > len(mejor.get(p[0], "")): mejor[p[0]] = p[1]      # el texto largo de la carta
        for h, t in mejor.items():
            if h in vistos_h: continue
            tok = [x.strip() for x in t.split(" / ") if x.strip()]
            if len(tok) < 4: continue
            ultimo = tok[-1]
            # transferible: '250K', '72.5K', '5K', '1.2M' o entero; un decimal sin K/M (p. ej. '88.0') = intransferible
            if not (re.fullmatch(r"\d+(?:\.\d+)?[KkMm]", ultimo) or re.fullmatch(r"\d+", ultimo)): continue
            mercado = precio(ultimo)
            try: media = int(tok[1])
            except ValueError: continue
            vistos_h.add(h)
            club.append({"href": h, "n": limpio(tok[0]), "r": media, "p": tok[2], "mercado": mercado})
    out["club"] = club
    out["club_paginas_leidas"] = paginas
    return out
