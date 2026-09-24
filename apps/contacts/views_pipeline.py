import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View

from apps.users.models import User

from .archivo import archivar, desarchivar
from .asignacion import asignar_agente
from .models import Contacto, Etapa, HistorialContacto, MotivoArchivo
from .pipeline import cambiar_etapa, puede_ver_contacto

POR_COLUMNA = 50
SIN_ETAPA = 'none'
ARCHIVADO = 'archivado'


def _filtros(request):
    return {
        'q': request.GET.get('q', '').strip(),
        'agente': request.GET.get('agente', '').strip() if request.user.can_see_all else '',
        'grupo': request.GET.get('grupo', '').strip(),
    }


def _contactos_qs(user, filtros):
    """Contactos visibles en el tablero: un agente solo ve los suyos."""
    qs = Contacto.objects.all()
    if not user.can_see_all:
        qs = qs.filter(agente=user)
    elif filtros['agente'] == 'sin':
        qs = qs.filter(agente__isnull=True)
    elif filtros['agente'].isdigit():
        qs = qs.filter(agente_id=int(filtros['agente']))
    if filtros['q']:
        q = filtros['q']
        qs = qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q) | Q(email__icontains=q))
    if filtros['grupo']:
        qs = qs.filter(grupo=filtros['grupo'])
    return qs


def _tarjetas(qs, etapa_key, offset=0):
    orden = F('etapa_actualizada_at').desc(nulls_last=True)
    if etapa_key == ARCHIVADO:
        qs = qs.filter(archivado=True)
        orden = F('archivado_at').desc(nulls_last=True)
    elif etapa_key == SIN_ETAPA:
        qs = qs.filter(archivado=False, etapa__isnull=True)
    else:
        qs = qs.filter(archivado=False, etapa_id=etapa_key)
    return list(
        qs.select_related('agente', 'etapa', 'archivado_motivo')
        .annotate(ultimo_msg=Max('conversaciones__ultimo_mensaje_at'), conv_id=Max('conversaciones__pk'))
        .order_by(orden, '-pk')[offset:offset + POR_COLUMNA]
    )


class KanbanView(LoginRequiredMixin, View):
    template_name = 'contacts/kanban.html'

    def get(self, request):
        filtros = _filtros(request)
        qs = _contactos_qs(request.user, filtros)
        conteos = {
            row['etapa_id']: row['n']
            for row in qs.filter(archivado=False).order_by().values('etapa_id').annotate(n=Count('pk'))
        }
        archivados = qs.filter(archivado=True).count()

        columnas = []
        if conteos.get(None):
            columnas.append({
                'key': SIN_ETAPA, 'nombre': 'Sin etapa', 'color': '#5a6478', 'tipo': 'abierta',
                'total': conteos[None], 'tarjetas': _tarjetas(qs, SIN_ETAPA),
            })
        for etapa in Etapa.objects.all():
            total = conteos.get(etapa.pk, 0)
            columnas.append({
                'key': etapa.pk, 'nombre': etapa.nombre, 'color': etapa.color, 'tipo': etapa.tipo,
                'total': total, 'tarjetas': _tarjetas(qs, etapa.pk) if total else [],
            })
        columnas.append({
            'key': ARCHIVADO, 'nombre': 'Archivado', 'color': '#5a6478', 'tipo': ARCHIVADO,
            'total': archivados, 'tarjetas': _tarjetas(qs, ARCHIVADO) if archivados else [],
        })

        ctx = {
            'columnas': columnas,
            'etapas': Etapa.objects.all(),
            'filtros': filtros,
            'total': sum(conteos.values()) + archivados,
            'motivos': MotivoArchivo.objects.filter(activo=True),
            'por_columna': POR_COLUMNA,
            'grupos': (
                Contacto.objects.exclude(grupo='').values_list('grupo', flat=True).distinct().order_by('grupo')
            ),
        }
        ctx['agentes'] = (
            User.objects.filter(is_active=True, rol=User.ROL_AGENTE).order_by('first_name', 'username')
            if request.user.can_see_all else None
        )
        return render(request, self.template_name, ctx)


class KanbanColumnaAPIView(LoginRequiredMixin, View):
    """Siguiente tanda de tarjetas de una columna ("Cargar más")."""

    def get(self, request):
        etapa_key = request.GET.get('etapa', '')
        if etapa_key not in (SIN_ETAPA, ARCHIVADO) and not etapa_key.isdigit():
            return JsonResponse({'ok': False, 'error': 'Etapa inválida'}, status=400)
        try:
            offset = max(0, int(request.GET.get('offset', 0)))
        except ValueError:
            offset = 0
        qs = _contactos_qs(request.user, _filtros(request))
        tarjetas = _tarjetas(qs, etapa_key, offset)
        html = ''.join(
            render_to_string('contacts/_kanban_card.html', {'c': c}, request=request) for c in tarjetas
        )
        return JsonResponse({'ok': True, 'html': html, 'cantidad': len(tarjetas)})


class ContactoEtapaView(LoginRequiredMixin, View):
    """Mueve un contacto de etapa (drag & drop del kanban, detalle del contacto o inbox)."""

    def post(self, request, pk):
        contacto = get_object_or_404(Contacto.objects.select_related('etapa'), pk=pk)
        if not puede_ver_contacto(request.user, contacto):
            return JsonResponse({'ok': False, 'error': 'Este contacto no está asignado a vos.'}, status=403)
        etapa = Etapa.objects.filter(pk=request.POST.get('etapa_id') or 0).first()
        if etapa is None:
            return JsonResponse({'ok': False, 'error': 'Etapa inválida.'}, status=400)
        # Mover una tarjeta archivada a una etapa la reactiva
        if contacto.archivado:
            desarchivar(contacto=contacto, usuario=request.user, detalle=f'Movido a {etapa.nombre}')
        cambiar_etapa(contacto, etapa, usuario=request.user)
        return JsonResponse({'ok': True, 'etapa': etapa.nombre})


class ContactoArchivarView(LoginRequiredMixin, View):
    """Archiva el contacto (y su conversación) con un motivo."""

    def post(self, request, pk):
        contacto = get_object_or_404(Contacto, pk=pk)
        if not puede_ver_contacto(request.user, contacto):
            return JsonResponse({'ok': False, 'error': 'Este contacto no está asignado a vos.'}, status=403)
        motivo = MotivoArchivo.objects.filter(pk=request.POST.get('motivo_id') or 0, activo=True).first()
        if motivo is None:
            return JsonResponse({'ok': False, 'error': 'Elegí un motivo.'}, status=400)
        archivar(contacto=contacto, motivo=motivo, comentario=request.POST.get('comentario', ''), usuario=request.user)
        return JsonResponse({'ok': True})


class ContactoDesarchivarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        contacto = get_object_or_404(Contacto, pk=pk)
        if not puede_ver_contacto(request.user, contacto):
            return JsonResponse({'ok': False, 'error': 'Este contacto no está asignado a vos.'}, status=403)
        desarchivar(contacto=contacto, usuario=request.user)
        return JsonResponse({'ok': True})


class ContactoAgenteView(LoginRequiredMixin, View):
    """El supervisor cambia el agente dueño del contacto (y de su conversación)."""

    def post(self, request, pk):
        if not request.user.can_see_all:
            return JsonResponse({'ok': False, 'error': 'Sin permisos'}, status=403)
        contacto = get_object_or_404(Contacto.objects.select_related('agente'), pk=pk)
        agente = User.objects.filter(pk=request.POST.get('agente_id') or 0, is_active=True).first()
        if agente is None:
            return JsonResponse({'ok': False, 'error': 'Elegí un agente activo.'}, status=400)
        asignar_agente(agente, contacto=contacto, usuario=request.user)
        return JsonResponse({'ok': True, 'agente_nombre': agente.get_full_name() or agente.username})


class EtapasView(LoginRequiredMixin, View):
    """Configuración de las etapas del pipeline (solo administradores)."""
    template_name = 'contacts/etapas.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_admin:
            return HttpResponseForbidden('Solo administradores.')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        # order_by explícito: Django no aplica Meta.ordering a consultas con agregación
        etapas = Etapa.objects.annotate(total=Count('contactos')).order_by('orden', 'pk')
        motivos = MotivoArchivo.objects.annotate(total=Count('contactos')).order_by('orden', 'pk')
        return render(request, self.template_name, {'etapas': etapas, 'tipos': Etapa.TIPOS, 'motivos': motivos})

    def post(self, request):
        accion = request.POST.get('accion', '')
        handler = {
            'crear': self._crear, 'editar': self._editar,
            'subir': self._mover, 'bajar': self._mover, 'eliminar': self._eliminar,
            'motivo_crear': self._motivo_crear, 'motivo_editar': self._motivo_editar,
            'motivo_eliminar': self._motivo_eliminar,
        }.get(accion)
        if handler:
            handler(request)
        return redirect('contacts:etapas')

    @staticmethod
    def _datos(request):
        nombre = request.POST.get('nombre', '').strip()[:80]
        color = request.POST.get('color', '').strip()
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            color = '#3b82f6'
        tipo = request.POST.get('tipo', Etapa.TIPO_ABIERTA)
        if tipo not in dict(Etapa.TIPOS):
            tipo = Etapa.TIPO_ABIERTA
        return nombre, color, tipo

    def _crear(self, request):
        nombre, color, tipo = self._datos(request)
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return
        ultimo = Etapa.objects.order_by('-orden').values_list('orden', flat=True).first()
        Etapa.objects.create(nombre=nombre, color=color, tipo=tipo, orden=(ultimo or 0) + 1)
        messages.success(request, f'Etapa "{nombre}" creada.')

    def _editar(self, request):
        etapa = get_object_or_404(Etapa, pk=request.POST.get('etapa_id') or 0)
        nombre, color, tipo = self._datos(request)
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return
        etapa.nombre, etapa.color, etapa.tipo = nombre, color, tipo
        etapa.save()
        messages.success(request, 'Etapa actualizada.')

    def _mover(self, request):
        etapas = list(Etapa.objects.all())
        idx = next((i for i, e in enumerate(etapas) if str(e.pk) == request.POST.get('etapa_id')), None)
        if idx is None:
            return
        destino = idx - 1 if request.POST.get('accion') == 'subir' else idx + 1
        if not 0 <= destino < len(etapas):
            return
        etapas[idx], etapas[destino] = etapas[destino], etapas[idx]
        with transaction.atomic():
            for orden, etapa in enumerate(etapas):
                if etapa.orden != orden:
                    Etapa.objects.filter(pk=etapa.pk).update(orden=orden)

    def _eliminar(self, request):
        etapa = get_object_or_404(Etapa, pk=request.POST.get('etapa_id') or 0)
        if Etapa.objects.count() <= 1:
            messages.error(request, 'Tiene que quedar al menos una etapa.')
            return
        destino = Etapa.objects.exclude(pk=etapa.pk).filter(pk=request.POST.get('mover_a') or 0).first()
        ids = list(etapa.contactos.values_list('pk', flat=True))
        if ids and destino is None:
            messages.error(request, 'Elegí a qué etapa pasan sus contactos.')
            return
        with transaction.atomic():
            if ids:
                Contacto.objects.filter(pk__in=ids).update(etapa=destino, etapa_actualizada_at=timezone.now())
                HistorialContacto.objects.bulk_create([
                    HistorialContacto(
                        contacto_id=cid, tipo=HistorialContacto.TIPO_ETAPA,
                        valor_anterior=etapa.nombre, valor_nuevo=destino.nombre,
                        etapa_nueva=destino, usuario=request.user,
                    )
                    for cid in ids
                ], batch_size=500)
            etapa.delete()
        messages.success(
            request,
            f'Etapa "{etapa.nombre}" eliminada.' + (f' {len(ids)} contactos pasaron a "{destino.nombre}".' if ids else ''),
        )

    # ── Motivos de archivo ──

    def _motivo_crear(self, request):
        nombre = request.POST.get('nombre', '').strip()[:80]
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return
        ultimo = MotivoArchivo.objects.order_by('-orden').values_list('orden', flat=True).first()
        MotivoArchivo.objects.create(nombre=nombre, orden=(ultimo or 0) + 1)
        messages.success(request, f'Motivo "{nombre}" creado.')

    def _motivo_editar(self, request):
        motivo = get_object_or_404(MotivoArchivo, pk=request.POST.get('motivo_id') or 0)
        nombre = request.POST.get('nombre', '').strip()[:80]
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return
        motivo.nombre = nombre
        motivo.activo = request.POST.get('activo') == 'on'
        motivo.save()
        messages.success(request, 'Motivo actualizado.')

    def _motivo_eliminar(self, request):
        motivo = get_object_or_404(MotivoArchivo, pk=request.POST.get('motivo_id') or 0)
        if motivo.contactos.exists():
            messages.error(request, f'"{motivo.nombre}" está en uso: desactivalo en vez de eliminarlo.')
            return
        motivo.delete()
        messages.success(request, f'Motivo "{motivo.nombre}" eliminado.')
