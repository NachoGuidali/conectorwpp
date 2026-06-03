import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.contacts.models import CampoPersonalizado, Contacto
from apps.whatsapp.models import PlantillaHSM

from apps.contacts.filtros import (
    FECHA_OPCIONES, OPERADORES_POR_TIPO,
    apply_filters, parse_filtros_from_post, parse_filtros_from_json,
)
from .models import Difusion, DifusionContacto

logger = logging.getLogger('apps.whatsapp')

OPERADORES_SIN_VALOR = {'es_verdadero', 'es_falso', 'tiene_valor'}


def _context_base():
    """Shared context for create/edit forms."""
    campos = list(
        CampoPersonalizado.objects.filter(activo=True)
        .order_by('orden', 'etiqueta')
        .values('pk', 'etiqueta', 'tipo', 'grupo')
    )
    grupos = list(
        Contacto.objects.values_list('grupo', flat=True)
        .distinct().exclude(grupo='').order_by('grupo')
    )
    plantillas = PlantillaHSM.objects.filter(activa=True).order_by('nombre')
    return {
        'campos_disponibles': campos,
        'grupos': grupos,
        'plantillas': plantillas,
        'fecha_opciones': FECHA_OPCIONES,
        'operadores_por_tipo': json.dumps(OPERADORES_POR_TIPO),
    }


# ──────────────────────────────────────────────
class DifusionListView(LoginRequiredMixin, View):
    def get(self, request):
        qs = Difusion.objects.select_related('creado_por').all()
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(nombre__icontains=q)
        estado = request.GET.get('estado', '').strip()
        if estado:
            qs = qs.filter(estado=estado)
        return render(request, 'difusiones/list.html', {
            'difusiones': qs[:100],
            'q': q,
            'estado': estado,
            'ESTADOS': Difusion.ESTADOS,
        })


# ──────────────────────────────────────────────
class DifusionCreateView(LoginRequiredMixin, View):
    template_name = 'difusiones/create.html'

    def get(self, request):
        ctx = _context_base()
        ctx['total_preview'] = 0
        return render(request, self.template_name, ctx)

    def post(self, request):
        nombre = request.POST.get('nombre', '').strip()
        mensaje = request.POST.get('mensaje', '').strip()
        plantilla_id = request.POST.get('plantilla_id', '').strip()
        accion = request.POST.get('accion', 'draft')

        if not nombre:
            messages.error(request, 'El nombre de la difusión es requerido.')
            ctx = _context_base()
            ctx['post_data'] = request.POST
            return render(request, self.template_name, ctx)

        if not mensaje and not plantilla_id:
            messages.error(request, 'Escribí un mensaje o seleccioná una plantilla.')
            ctx = _context_base()
            ctx['post_data'] = request.POST
            return render(request, self.template_name, ctx)

        # Parse plantilla variables
        variables = []
        if plantilla_id:
            try:
                plantilla = PlantillaHSM.objects.get(pk=plantilla_id)
                variables = [
                    request.POST.get(f'var_{i + 1}', '')
                    for i in range(len(plantilla.variables or []))
                ]
            except PlantillaHSM.DoesNotExist:
                plantilla = None
        else:
            plantilla = None

        # Parse filtros
        filtros = parse_filtros_from_post(request.POST)

        # Resolve matching contacts
        contactos_qs = apply_filters(filtros)
        contactos = list(contactos_qs.values('pk', 'telefono', 'nombre'))

        if not contactos:
            messages.warning(request, 'No hay contactos que coincidan con los filtros.')
            ctx = _context_base()
            ctx['post_data'] = request.POST
            return render(request, self.template_name, ctx)

        # Create Difusion
        difusion = Difusion.objects.create(
            nombre=nombre,
            mensaje=mensaje,
            plantilla=plantilla,
            variables_plantilla=variables,
            filtros=filtros,
            estado=Difusion.ESTADO_BORRADOR,
            total=len(contactos),
            creado_por=request.user,
        )

        # Create DifusionContacto bulk
        DifusionContacto.objects.bulk_create([
            DifusionContacto(
                difusion=difusion,
                contacto_id=c['pk'],
                telefono=c['telefono'],
                nombre=c['nombre'],
            )
            for c in contactos
        ], ignore_conflicts=True)

        if accion == 'send':
            return redirect('difusiones:enviar', pk=difusion.pk)

        messages.success(request, f'Difusión "{nombre}" creada con {len(contactos)} destinatarios.')
        return redirect('difusiones:detail', pk=difusion.pk)


# ──────────────────────────────────────────────
class DifusionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        difusion = get_object_or_404(Difusion.objects.select_related('plantilla', 'creado_por'), pk=pk)

        q = request.GET.get('q', '').strip()
        dest_qs = difusion.destinatarios.all()
        if q:
            dest_qs = dest_qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q))
        estado_f = request.GET.get('estado_f', '').strip()
        if estado_f:
            dest_qs = dest_qs.filter(estado=estado_f)

        total_dest = difusion.destinatarios.count()
        page = max(1, int(request.GET.get('p', 1) or 1))
        per_page = 50
        offset = (page - 1) * per_page
        destinatarios = list(dest_qs.select_related('contacto')[offset:offset + per_page])

        return render(request, 'difusiones/detail.html', {
            'difusion': difusion,
            'destinatarios': destinatarios,
            'total_dest': total_dest,
            'q': q,
            'estado_f': estado_f,
            'page': page,
            'has_prev': page > 1,
            'has_next': offset + per_page < dest_qs.count(),
            'prev_page': page - 1,
            'next_page': page + 1,
            'mensaje_preview': difusion.get_mensaje_texto(),
        })


# ──────────────────────────────────────────────
class DifusionEnviarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        difusion = get_object_or_404(Difusion, pk=pk)

        if difusion.estado != Difusion.ESTADO_BORRADOR:
            messages.error(request, f'Esta difusión ya está en estado "{difusion.get_estado_display()}".')
            return redirect('difusiones:detail', pk=pk)

        if not difusion.total:
            messages.error(request, 'No hay destinatarios en esta difusión.')
            return redirect('difusiones:detail', pk=pk)

        from .tasks import send_difusion_task
        send_difusion_task.delay(difusion.pk)
        messages.success(request, f'Enviando difusión a {difusion.total} contactos...')
        return redirect('difusiones:detail', pk=pk)


# ──────────────────────────────────────────────
class DifusionEliminarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        difusion = get_object_or_404(Difusion, pk=pk)
        if difusion.estado == Difusion.ESTADO_ENVIANDO:
            messages.error(request, 'No se puede eliminar una difusión en curso.')
            return redirect('difusiones:detail', pk=pk)
        nombre = difusion.nombre
        difusion.delete()
        messages.success(request, f'Difusión "{nombre}" eliminada.')
        return redirect('difusiones:list')


# ──────────────────────────────────────────────
# API: preview de contactos matching filtros
# ──────────────────────────────────────────────
@method_decorator(csrf_exempt, name='dispatch')
class PreviewContactosAPIView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
        except Exception:
            data = request.POST.dict()

        filtros = parse_filtros_from_json(data)
        qs = apply_filters(filtros)
        total = qs.count()
        muestra = list(qs.values('nombre', 'telefono')[:8])
        return JsonResponse({'total': total, 'muestra': muestra})
