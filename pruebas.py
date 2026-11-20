"""python pruebas.py  -> no usa red ni Telegram. Debe imprimir OK."""
import analizar, confirmar
assert analizar.precio("72.5K") == 72500 and analizar.precio("1.2M") == 1200000
assert analizar.precio("950") == 950 and analizar.precio("EXTINCT") is None
O = {"compra": "p25", "gan_min": 300, "pct_min": 4, "ventas_min": 10, "recencia_min": 180}
c = {"n": "X", "r": "85", "t": "Rare", "p": "CM", "href": "/h", "pc": 2000}
b = {"precio_actual": 2000, "venta_min": 1900, "venta_max": 2800, "ventas_buynow_n": 80, "ventas_span_h": 2,
     "ventas_por_hora": 40, "ultima_venta_hace_min": 3, "venta_p25": 2000}
assert confirmar.veredicto(c, dict(b, venta_mediana=2600, venta_mediana_15=2600), O)["ok"] is True    # 2.470 - 2.000 = 470
assert confirmar.veredicto(c, dict(b, venta_mediana=2600, venta_mediana_15=2100), O)["ok"] is False   # el mercado ya bajo
assert confirmar.veredicto(c, dict(b, venta_mediana=2600, venta_mediana_15=2600, ultima_venta_hace_min=600), O)["ok"] is False
print("OK")
