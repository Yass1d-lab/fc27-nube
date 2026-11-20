"""Guarda y recupera la memoria del script entre lecturas en GitHub Actions.
  python nube.py antes    -> copia estado_nube/ (cache de GitHub) a la carpeta; si no hay, usa semilla/
  python nube.py despues  -> copia la memoria de esta lectura a estado_nube/ para la siguiente
Solo maneja datos publicos de FUT.GG (precios). Nada del GG Club ni de config.ini."""
import os, shutil, sys
BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "estado_nube")
SEMILLA = os.path.join(BASE, "semilla")
ARCHIVOS = ["estado.json", "amplio.json", "confirmadas_avisadas.json", "bloqueo.txt"]

def copiar(origen, destino):
    n = 0
    for a in ARCHIVOS:
        o = os.path.join(origen, a)
        if os.path.exists(o):
            shutil.copy2(o, os.path.join(destino, a)); n += 1   # copy2 conserva la hora (la pausa de 2 h la usa)
    return n

if __name__ == "__main__":
    paso = sys.argv[1] if len(sys.argv) > 1 else ""
    if paso == "antes":
        if os.path.isdir(CACHE) and os.listdir(CACHE):
            print("Memoria recuperada de la lectura anterior:", copiar(CACHE, BASE), "archivos")
        else:
            print("Primera lectura: uso la semilla:", copiar(SEMILLA, BASE), "archivos")
        os.makedirs(os.path.join(BASE, "datos"), exist_ok=True)
    elif paso == "despues":
        os.makedirs(CACHE, exist_ok=True)
        print("Memoria guardada:", copiar(BASE, CACHE), "archivos")
    else:
        print(__doc__)
