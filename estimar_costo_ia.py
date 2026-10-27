"""
Estimación de costo de IA para atender conversaciones de ventas.

Uso en el servidor:
    docker compose exec web python estimar_costo_ia.py

Lógica:
  - Por cada turno del usuario, el bot recibiría:
      system prompt + historial hasta ese punto  →  input tokens
      respuesta del bot (~100 tokens promedio)   →  output tokens
  - Sumamos todo y multiplicamos por el precio de cada modelo.
  - Solo cuenta conversaciones con al menos 2 mensajes (conversaciones reales).
"""

import os, sys, django

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.whatsapp.models import Conversacion, Mensaje
from django.db.models import Count, Prefetch

# ── Parámetros del estimado ──────────────────────────────────────────────────

SYSTEM_PROMPT_TOKENS = 600      # prompt del sistema del bot (aprox)
OUTPUT_TOKENS_POR_TURNO = 100   # respuesta promedio del bot por turno
CHARS_POR_TOKEN = 3.5           # aprox para español

# Modelos y precios (USD por millón de tokens)
MODELOS = [
    # (nombre,                input $/M,  output $/M)
    ('GPT-4o mini',              0.15,       0.60),
    ('GPT-4o',                   2.50,      10.00),
    ('Claude Haiku 3.5',         0.80,       4.00),
    ('Claude Sonnet 4.5',        3.00,      15.00),
    ('Groq Llama 3.1 8B',        0.05,       0.08),
    ('Groq Llama 3.3 70B',       0.59,       0.79),
]

# ── Análisis de conversaciones ───────────────────────────────────────────────

convs = (
    Conversacion.objects
    .prefetch_related(
        Prefetch('mensajes', queryset=Mensaje.objects.filter(tipo='text').order_by('timestamp'))
    )
    .annotate(n_msgs=Count('mensajes'))
    .filter(n_msgs__gte=2)
)

total_convs = 0
total_input_tokens = 0
total_output_tokens = 0
tokens_por_conv = []

for conv in convs:
    msgs = list(conv.mensajes.all())
    if not msgs:
        continue

    historial_chars = 0
    input_tokens_conv = 0
    output_tokens_conv = 0
    turnos_usuario = 0

    for msg in msgs:
        chars = len(msg.contenido or '')
        if msg.direccion == 'in':
            # Turno del usuario: el bot procesa system + historial + este mensaje
            ctx_tokens = SYSTEM_PROMPT_TOKENS + int((historial_chars + chars) / CHARS_POR_TOKEN)
            input_tokens_conv += ctx_tokens
            output_tokens_conv += OUTPUT_TOKENS_POR_TURNO
            turnos_usuario += 1
        historial_chars += chars + 20  # +20 por separadores "Usuario:" / "Bot:"

    if turnos_usuario == 0:
        continue

    total_convs += 1
    total_input_tokens += input_tokens_conv
    total_output_tokens += output_tokens_conv
    tokens_por_conv.append((input_tokens_conv + output_tokens_conv, turnos_usuario))

# ── Estadísticas ─────────────────────────────────────────────────────────────

if not tokens_por_conv:
    print("No se encontraron conversaciones con mensajes.")
    sys.exit(0)

tokens_por_conv.sort()
total_tokens = total_input_tokens + total_output_tokens
avg_tokens = total_tokens / total_convs
avg_turnos = sum(t for _, t in tokens_por_conv) / total_convs
mediana_tokens = tokens_por_conv[len(tokens_por_conv) // 2][0]

print("=" * 62)
print("  ESTIMACIÓN DE COSTO IA — CONVERSACIONES DE VENTAS")
print("=" * 62)
print(f"  Conversaciones analizadas : {total_convs:,}")
print(f"  Turnos promedio por conv  : {avg_turnos:.1f}")
print(f"  Tokens promedio por conv  : {avg_tokens:,.0f}")
print(f"  Tokens mediana por conv   : {mediana_tokens:,.0f}")
print(f"  Total tokens input        : {total_input_tokens:,}")
print(f"  Total tokens output       : {total_output_tokens:,}")
print()
print(f"  {'Modelo':<25} {'Por conv':>10}  {'Total':>12}  {'x1000 convs':>13}")
print("  " + "-" * 62)

for nombre, p_in, p_out in MODELOS:
    costo_total = (total_input_tokens / 1_000_000 * p_in) + (total_output_tokens / 1_000_000 * p_out)
    costo_por_conv = costo_total / total_convs if total_convs else 0
    costo_1000 = costo_por_conv * 1000
    print(f"  {nombre:<25} ${costo_por_conv:>8.4f}  ${costo_total:>10.3f}  ${costo_1000:>11.2f}")

print()
print("  * 'Total' = costo si el bot hubiera atendido TODAS las convs actuales")
print("  * 'x1000 convs' = estimado mensual con 1000 conversaciones nuevas")
print("=" * 62)
