import configparser, json, os, shutil, time, urllib.parse, urllib.request
BASE = os.path.dirname(os.path.abspath(__file__))
NUBE = os.environ.get("FC27_NUBE") == "1"   # True cuando corre en GitHub Actions (sin GG Club)
def cfg():
    c = configparser.ConfigParser()
    # config.ini = tuyo (token de Telegram, reglas). opciones.ini = ajustes que cambia Claude; si existe, se lee despues.
    c.read([os.path.join(BASE, "config.ini"), os.path.join(BASE, "opciones.ini")], encoding="utf-8-sig")
    return c
def telegram(texto):
    """Devuelve True si Telegram acepto el mensaje. Reintenta 1 vez. No imprime la URL (lleva el token)."""
    # En la nube (GitHub) el token y el chat_id vienen de los Secrets, no de config.ini
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat):
        try:
            c = cfg()
            token = c.get("telegram", "token").strip()
            chat = c.get("telegram", "chat_id").strip()
        except Exception:
            print("Telegram sin configurar (faltan los Secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID)")
            return False
    if NUBE:
        texto = "☁️ " + texto
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": texto[:4000]}).encode()
    for intento in (1, 2):
        try:
            urllib.request.urlopen(url, data=data, timeout=20).read()
            return True
        except Exception as e:
            print(f"Telegram fallo (intento {intento}): {type(e).__name__}")
            time.sleep(5)
    return False


def guardar_json(ruta, obj, indent=None):
    """Escritura segura: archivo temporal, copia .bak del anterior y reemplazo atomico."""
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(ruta):
        try: shutil.copy2(ruta, ruta + ".bak")
        except Exception: pass
    os.replace(tmp, ruta)


def cargar_json(ruta, defecto):
    """Lee el JSON; si esta danado usa el .bak; si tampoco, devuelve defecto."""
    for r in (ruta, ruta + ".bak"):
        try:
            with open(r, encoding="utf-8") as f: return json.load(f)
        except FileNotFoundError: continue
        except Exception as e: print("JSON danado:", os.path.basename(r), type(e).__name__)
    return defecto
