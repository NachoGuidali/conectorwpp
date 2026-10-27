"""
Estimación de costo de IA para atender conversaciones de ventas.

Uso en el servidor:
    docker compose exec web python estimar_costo_ia.py
"""

import os, sys, django

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.whatsapp.models import Conversacion, Mensaje
from django.db.models import Count, Prefetch

# ── Parámetros base ──────────────────────────────────────────────────────────
SYSTEM_PROMPT_TOKENS = 600
OUTPUT_TOKENS_POR_TURNO = 100
CHARS_POR_TOKEN = 3.5

# ── Parámetros escenario complejo ────────────────────────────────────────────
# System prompt más largo (instrucciones de venta, ejemplos, reglas)
SYSTEM_PROMPT_COMPLEJO = 1_800
# Respuesta más elaborada (argumenta, consulta datos, cierra venta)
OUTPUT_COMPLEJO_POR_TURNO = 250
# Tokens de datos de BD inyectados por conversación (planes, precios, historial cliente)
TOKENS_DB_POR_CONV = 1_500
# % de conversaciones con imagen (recibo, DNI, documento)
PCT_IMAGENES = 0.30
# Tokens que consume una imagen típica (resolución media)
TOKENS_POR_IMAGEN_GPT = 1_000   # GPT-4o / GPT-4o mini (low-detail ~85, high ~765-1700)
TOKENS_POR_IMAGEN_CLAUDE = 1_600  # Claude Haiku / Sonnet

# Modelos: (nombre, input $/M, output $/M, soporta_vision)
MODELOS = [
    ('GPT-4o mini',       0.15,   0.60,  True),
    ('GPT-4o',            2.50,  10.00,  True),
    ('Claude Haiku 3.5',  0.80,   4.00,  True),
    ('Claude Sonnet 4.5', 3.00,  15.00,  True),
    ('Groq Llama 3.3 70B',0.59,   0.79,  False),  # sin visión nativa
]

# ── Leer conversaciones ──────────────────────────────────────────────────────
convs = (
    Conversacion.objects
    .prefetch_related(
        Prefetch('mensajes', queryset=Mensaje.objects.filter(tipo='text').order_by('timestamp'))
    )
    .annotate(n_msgs=Count('mensajes'))
    .filter(n_msgs__gte=2)
)

total_convs = 0
base_in = base_out = 0
tokens_por_conv = []

for conv in convs:
    msgs = list(conv.mensajes.all())
    if not msgs:
        continue
    historial_chars = 0
    in_conv = out_conv = turnos = 0
    for msg in msgs:
        chars = len(msg.contenido or '')
        if msg.direccion == 'in':
            in_conv += SYSTEM_PROMPT_TOKENS + int((historial_chars + chars) / CHARS_POR_TOKEN)
            out_conv += OUTPUT_TOKENS_POR_TURNO
            turnos += 1
        historial_chars += chars + 20
    if not turnos:
        continue
    total_convs += 1
    base_in += in_conv
    base_out += out_conv
    tokens_por_conv.append((in_conv + out_conv, turnos))

if not tokens_por_conv:
    print("No se encontraron conversaciones.")
    sys.exit(0)

tokens_por_conv.sort()
avg_tokens = (base_in + base_out) / total_convs
avg_turnos = sum(t for _, t in tokens_por_conv) / total_convs
mediana = tokens_por_conv[len(tokens_por_conv) // 2][0]

# ── Escenarios ───────────────────────────────────────────────────────────────
# Factor de escala para pasar de parámetros base a complejos
factor_in = (
    (SYSTEM_PROMPT_COMPLEJO / SYSTEM_PROMPT_TOKENS) * 0.6   # prompt pesa ~60% del input
    + 0.4                                                    # historial no cambia
)
factor_out = OUTPUT_COMPLEJO_POR_TURNO / OUTPUT_TOKENS_POR_TURNO

complejo_in  = base_in  * factor_in  + total_convs * TOKENS_DB_POR_CONV
complejo_out = base_out * factor_out

def costo_escenario(inp, out, p_in, p_out, vision, img_tokens):
    img_extra = total_convs * PCT_IMAGENES * img_tokens if vision else \
                total_convs * PCT_IMAGENES * TOKENS_POR_IMAGEN_GPT * (0.15 / 1e6) * 1e6  # Groq usa GPT mini para imágenes
    if vision:
        inp_total = inp + total_convs * PCT_IMAGENES * img_tokens
    else:
        # Sin visión nativa: llama a GPT-4o mini solo para procesar imágenes
        inp_total = inp
    costo = inp_total / 1e6 * p_in + out / 1e6 * p_out
    if not vision:
        # Costo extra por delegar imágenes a GPT-4o mini
        costo += total_convs * PCT_IMAGENES * TOKENS_POR_IMAGEN_GPT / 1e6 * 0.15
    return costo

# ── Imprimir ─────────────────────────────────────────────────────────────────
W = 70
print("=" * W)
print("  ESTIMACIÓN DE COSTO IA — CONVERSACIONES DE VENTAS")
print("=" * W)
print(f"  Conversaciones analizadas : {total_convs:,}")
print(f"  Turnos promedio por conv  : {avg_turnos:.1f}")
print(f"  Tokens promedio por conv  : {avg_tokens:,.0f}  (mediana: {mediana:,.0f})")
print(f"  Total tokens input/output : {base_in:,} / {base_out:,}")
print()

SCENARIOS = [
    ('BASE (actual)',          base_in,     base_out,     False),
    ('COMPLEJO (BD, +detalle)',complejo_in, complejo_out, False),
    ('COMPLEJO + IMÁGENES',    complejo_in, complejo_out, True),
]

hdr = f"  {'Modelo':<22} {'BASE /conv':>10} {'COMPLEJO /conv':>15} {'COMPLEJO+IMG /conv':>19} {'x1000/mes':>10}"
print(hdr)
print("  " + "-" * (W - 2))

for nombre, p_in, p_out, vision in MODELOS:
    img_tok = TOKENS_POR_IMAGEN_CLAUDE if 'Claude' in nombre else TOKENS_POR_IMAGEN_GPT
    costos = []
    for label, inp, out, with_img in SCENARIOS:
        c = (inp / 1e6 * p_in + out / 1e6 * p_out)
        if with_img:
            if vision:
                c += total_convs * PCT_IMAGENES * img_tok / 1e6 * p_in
            else:
                c += total_convs * PCT_IMAGENES * TOKENS_POR_IMAGEN_GPT / 1e6 * 0.15
        costos.append(c / total_convs)

    c1000 = costos[2] * 1000
    print(f"  {nombre:<22} ${costos[0]:>8.4f}  ${costos[1]:>13.4f}  ${costos[2]:>17.4f}  ${c1000:>8.2f}")

print()
print(f"  Supuestos escenario COMPLEJO:")
print(f"    · System prompt: {SYSTEM_PROMPT_COMPLEJO} tokens  (base: {SYSTEM_PROMPT_TOKENS})")
print(f"    · Output por turno: {OUTPUT_COMPLEJO_POR_TURNO} tokens  (base: {OUTPUT_TOKENS_POR_TURNO})")
print(f"    · Datos de BD por conv: ~{TOKENS_DB_POR_CONV} tokens")
print(f"    · Imágenes: {int(PCT_IMAGENES*100)}% de convs × 1 imagen")
print(f"    · Groq sin visión: delega imágenes a GPT-4o mini")
print("=" * W)
