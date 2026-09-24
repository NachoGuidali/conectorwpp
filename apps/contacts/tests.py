import json
from io import StringIO
from unittest import mock

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.contacts.models import Contacto, Etapa, HistorialContacto
from apps.users.models import User
from apps.whatsapp.models import Conversacion


def _agente(username, **kw):
    return User.objects.create_user(username=username, password='x', rol=User.ROL_AGENTE, **kw)


class Base(TestCase):
    def setUp(self):
        self.a1 = _agente('a1')
        self.a2 = _agente('a2')
        self.sup = User.objects.create_user(username='sup', password='x', rol=User.ROL_SUPERVISOR)
        self.admin = User.objects.create_user(username='adm', password='x', rol=User.ROL_ADMIN)

    def entrante(self, phone, nombre='Cliente'):
        from apps.whatsapp.tasks import process_incoming_message
        with mock.patch('apps.whatsapp.tasks.forward_to_n8n_task'):
            process_incoming_message.apply(args=[{
                'from_phone': phone.lstrip('+'), 'message_id': f'id-{phone}-{timezone.now().timestamp()}',
                'type': 'text', 'content': 'hola', 'timestamp': timezone.now(), 'contact_name': nombre,
            }])
        return Conversacion.objects.select_related('contacto').get(telefono=phone)


class EtapasInicialesTests(Base):
    def test_migracion_crea_etapas_y_contacto_nuevo_entra_en_la_primera(self):
        self.assertEqual(
            list(Etapa.objects.values_list('nombre', flat=True)),
            ['Nuevo', 'Contactado', 'Interesado', 'Negociación', 'Ganado', 'Perdido'],
        )
        c = Contacto.objects.create(nombre='X', telefono='+1')
        self.assertEqual(c.etapa.nombre, 'Nuevo')
        self.assertIsNotNone(c.etapa_actualizada_at)

    def test_migracion_copia_agente_de_la_conversacion(self):
        from importlib import import_module
        mig = import_module('apps.contacts.migrations.0003_datos_pipeline')
        c = Contacto.objects.create(nombre='X', telefono='+1')
        Conversacion.objects.create(telefono='+1', contacto=c, agente=self.a2)
        mig.copiar_agente_de_conversacion(django_apps, None)
        c.refresh_from_db()
        self.assertEqual(c.agente, self.a2)


class EntrantesTests(Base):
    def test_entrante_nuevo_contacto_y_conversacion_con_mismo_agente(self):
        conv = self.entrante('+5491100000001')
        self.assertIsNotNone(conv.agente)
        self.assertEqual(conv.contacto.agente, conv.agente)
        self.assertEqual(conv.contacto.etapa.nombre, 'Nuevo')

    def test_entrante_de_contacto_existente_va_a_su_dueno(self):
        c = Contacto.objects.create(nombre='X', telefono='+5491100000002', agente=self.a2)
        # a2 tiene más carga, igual debe quedar con a2 por ser el dueño
        Conversacion.objects.create(telefono='+999', agente=self.a2)
        conv = self.entrante(c.telefono)
        self.assertEqual(conv.agente, self.a2)

    def test_conversacion_archivada_de_agente_inactivo_se_reasigna(self):
        c = Contacto.objects.create(nombre='X', telefono='+5491100000003', agente=self.a1)
        Conversacion.objects.create(telefono=c.telefono, contacto=c, agente=self.a1, archivada=True)
        User.objects.filter(pk=self.a1.pk).update(is_active=False)
        conv = self.entrante(c.telefono)
        self.assertEqual(conv.agente, self.a2)
        c.refresh_from_db()
        self.assertEqual(c.agente, self.a2)

    def test_si_nadie_recibe_asignaciones_igual_se_asigna(self):
        User.objects.filter(rol=User.ROL_AGENTE).update(recibe_asignaciones=False, en_turno=False)
        conv = self.entrante('+5491100000004')
        self.assertIn(conv.agente, [self.a1, self.a2])

    def test_sin_agentes_activos_queda_sin_agente_y_la_tarea_lo_reintenta(self):
        from apps.whatsapp.tasks import asignar_conversaciones_sin_agente
        User.objects.filter(rol=User.ROL_AGENTE).update(is_active=False)
        conv = self.entrante('+5491100000005')
        self.assertIsNone(conv.agente)
        User.objects.filter(pk=self.a1.pk).update(is_active=True)
        asignar_conversaciones_sin_agente()
        conv.refresh_from_db()
        self.assertEqual(conv.agente, self.a1)
        self.assertEqual(Contacto.objects.get(telefono=conv.telefono).agente, self.a1)


class SalientesTests(Base):
    def test_nueva_conversacion_de_agente_queda_para_el(self):
        self.client.force_login(self.a2)
        self.client.post(reverse('whatsapp:nueva_conversacion'), {'telefono': '+5491100000010', 'nombre': 'N'})
        conv = Conversacion.objects.get(telefono='+5491100000010')
        self.assertEqual(conv.agente, self.a2)
        self.assertEqual(conv.contacto.agente, self.a2)
        self.assertEqual(conv.origen_conversacion, Conversacion.ORIGEN_SALIENTE)

    def test_agente_no_puede_quedarse_con_contacto_de_otro(self):
        c = Contacto.objects.create(nombre='X', telefono='+5491100000011', agente=self.a1)
        self.client.force_login(self.a2)
        r = self.client.post(reverse('whatsapp:nueva_conversacion'), {'contacto_id': c.pk})
        self.assertRedirects(r, reverse('whatsapp:inbox'), fetch_redirect_response=False)
        self.assertEqual(Conversacion.objects.get(telefono=c.telefono).agente, self.a1)

    def test_deep_link_de_supervisor_no_deja_sin_agente(self):
        self.client.force_login(self.sup)
        self.client.get(reverse('whatsapp:ir_a_conversacion', args=['5491100000012']))
        conv = Conversacion.objects.get(telefono='+5491100000012')
        self.assertIn(conv.agente, [self.a1, self.a2])
        self.assertEqual(conv.contacto.agente, conv.agente)

    @override_settings(CRM_API_KEY='k')
    def test_api_enviar_crea_contacto_con_agente_y_no_desarchiva(self):
        with mock.patch('apps.whatsapp.sender.send_text_message', return_value={'id': 'm1'}):
            r = self.client.post(
                reverse('whatsapp:api_enviar'), data=json.dumps({'phone': '5491100000013', 'message': 'hola'}),
                content_type='application/json', HTTP_X_API_KEY='k',
            )
        self.assertEqual(r.status_code, 200, r.content)
        conv = Conversacion.objects.get(telefono='+5491100000013')
        self.assertIsNotNone(conv.agente)
        self.assertEqual(conv.contacto.agente, conv.agente)

        Conversacion.objects.filter(pk=conv.pk).update(archivada=True)
        with mock.patch('apps.whatsapp.sender.send_text_message', return_value={'id': 'm2'}):
            self.client.post(
                reverse('whatsapp:api_enviar'), data=json.dumps({'phone': '5491100000013', 'message': 'hola'}),
                content_type='application/json', HTTP_X_API_KEY='k',
            )
        conv.refresh_from_db()
        self.assertTrue(conv.archivada)

    def test_difusion_asigna_dueno_y_origen_saliente(self):
        from apps.difusiones.models import Difusion, DifusionContacto
        from apps.difusiones.tasks import send_difusion_task
        con_dueno = Contacto.objects.create(nombre='A', telefono='+5491100000020', agente=self.a2)
        sin_dueno = Contacto.objects.create(nombre='B', telefono='+5491100000021')
        d = Difusion.objects.create(nombre='d', mensaje='hola', creado_por=self.a1)
        for c in (con_dueno, sin_dueno):
            DifusionContacto.objects.create(difusion=d, contacto=c, telefono=c.telefono, nombre=c.nombre)
        with mock.patch('apps.whatsapp.sender.send_text_message', return_value={'id': 'x'}), \
                mock.patch('apps.difusiones.tasks.time.sleep'):
            send_difusion_task.apply(args=[d.pk])
        c1 = Conversacion.objects.get(telefono=con_dueno.telefono)
        c2 = Conversacion.objects.get(telefono=sin_dueno.telefono)
        self.assertEqual(c1.agente, self.a2)           # respeta al dueño
        self.assertEqual(c2.agente, self.a1)           # sin dueño → quien creó la difusión
        self.assertEqual(Contacto.objects.get(pk=sin_dueno.pk).agente, self.a1)
        self.assertEqual(c1.origen_conversacion, Conversacion.ORIGEN_SALIENTE)


class ReasignacionTests(Base):
    def test_supervisor_no_puede_dejar_sin_agente_y_sincroniza_contacto(self):
        c = Contacto.objects.create(nombre='X', telefono='+1', agente=self.a1)
        conv = Conversacion.objects.create(telefono='+1', contacto=c, agente=self.a1)
        self.client.force_login(self.sup)
        url = reverse('whatsapp:asignar_agente', args=[conv.pk])
        self.assertEqual(self.client.post(url, {'agente_id': ''}).status_code, 400)
        self.assertEqual(self.client.post(url, {'agente_id': self.a2.pk}).status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.agente, self.a2)
        h = HistorialContacto.objects.get(contacto=c, tipo='agente')
        self.assertEqual((h.valor_anterior, h.valor_nuevo, h.usuario), ('a1', 'a2', self.sup))

    def test_redistribuir_sin_otro_agente_no_toca_nada(self):
        User.objects.filter(pk=self.a2.pk).update(is_active=False)
        conv = Conversacion.objects.create(telefono='+1', agente=self.a1)
        self.client.force_login(self.sup)
        self.client.post(reverse('whatsapp:dashboard_supervisor'), {'desde_agente': self.a1.pk})
        conv.refresh_from_db()
        self.assertEqual(conv.agente, self.a1)

    def test_reasignar_desde_hacia_mueve_contactos_y_cuenta_bien(self):
        c = Contacto.objects.create(nombre='X', telefono='+1', agente=self.a1)
        Conversacion.objects.create(telefono='+1', contacto=c, agente=self.a1)
        self.client.force_login(self.sup)
        r = self.client.post(
            reverse('whatsapp:dashboard_supervisor'), {'desde_agente': self.a1.pk, 'hacia_agente': self.a2.pk},
            follow=True,
        )
        self.assertContains(r, '1 conversaciones reasignadas')
        c.refresh_from_db()
        self.assertEqual(c.agente, self.a2)

    def test_desactivar_agente_reparte_toda_su_cartera(self):
        a3 = _agente('a3')
        solo_contacto = Contacto.objects.create(nombre='S', telefono='+1', agente=self.a1)
        archivado = Contacto.objects.create(nombre='A', telefono='+2', agente=self.a1)
        Conversacion.objects.create(telefono='+2', contacto=archivado, agente=self.a1, archivada=True)
        abierta = Conversacion.objects.create(telefono='+3', agente=self.a1)
        self.client.force_login(self.admin)
        self.client.post(reverse('users:toggle', args=[self.a1.pk]))
        for obj in (solo_contacto, archivado, abierta):
            obj.refresh_from_db()
            self.assertIn(obj.agente, [self.a2, a3])
        self.assertEqual(Conversacion.objects.get(telefono='+2').agente, archivado.agente)
        self.assertFalse(Contacto.objects.filter(agente=self.a1).exists())

    def test_borrar_usuario_no_deja_huerfanos(self):
        c = Contacto.objects.create(nombre='X', telefono='+1', agente=self.a1)
        Conversacion.objects.create(telefono='+1', contacto=c, agente=self.a1)
        self.a1.delete()
        c.refresh_from_db()
        self.assertEqual(c.agente, self.a2)
        self.assertEqual(Conversacion.objects.get(telefono='+1').agente, self.a2)


class ContactosTests(Base):
    def test_alta_manual_por_agente_queda_para_el(self):
        self.client.force_login(self.a2)
        self.client.post(reverse('contacts:create'), {'nombre': 'N', 'telefono': '+5491100000030'})
        self.assertEqual(Contacto.objects.get(telefono='+5491100000030').agente, self.a2)

    def test_alta_manual_por_supervisor_con_agente_elegido(self):
        self.client.force_login(self.sup)
        self.client.post(reverse('contacts:create'), {'nombre': 'N', 'telefono': '+5491100000031', 'agente_id': self.a1.pk})
        self.assertEqual(Contacto.objects.get(telefono='+5491100000031').agente, self.a1)

    def test_alta_manual_con_conversacion_existente_toma_su_agente(self):
        Conversacion.objects.create(telefono='+5491100000032', agente=self.a2)
        self.client.force_login(self.sup)
        self.client.post(reverse('contacts:create'), {'nombre': 'N', 'telefono': '+5491100000032', 'agente_id': self.a1.pk})
        c = Contacto.objects.get(telefono='+5491100000032')
        self.assertEqual(c.agente, self.a2)
        self.assertEqual(Conversacion.objects.get(telefono=c.telefono).contacto, c)

    def test_importacion_reparte_y_respeta_duenos(self):
        from apps.contacts.importar import import_from_rows
        from apps.contacts.views import _asignador_importacion
        existente = Contacto.objects.create(nombre='E', telefono='+5491100000040', agente=self.a2)
        request = mock.Mock(user=self.sup, POST={})
        rows = [['E', '+5491100000040']] + [[f'N{i}', f'+54911000001{i:02d}'] for i in range(10)]
        import_from_rows(['nombre', 'telefono'], rows, {'0': 'nombre', '1': 'telefono'}, {},
                         asignador=_asignador_importacion(request))
        existente.refresh_from_db()
        self.assertEqual(existente.agente, self.a2)
        nuevos = Contacto.objects.exclude(pk=existente.pk)
        self.assertFalse(nuevos.filter(agente__isnull=True).exists())
        self.assertEqual(nuevos.filter(agente=self.a1).count(), 5)
        self.assertEqual(nuevos.filter(agente=self.a2).count(), 5)

    @override_settings(CRM_API_KEY='k')
    def test_api_contacto_asigna_dueno_y_etapa(self):
        r = self.client.post(
            reverse('whatsapp:api_contacto'),
            data=json.dumps({'phone': '5491100000050', 'nombre': 'Z', 'etapa': 'interesado'}),
            content_type='application/json', HTTP_X_API_KEY='k',
        )
        data = r.json()
        c = Contacto.objects.get(telefono='+5491100000050')
        self.assertIsNotNone(c.agente)
        self.assertEqual(c.etapa.nombre, 'Interesado')
        self.assertEqual(data['etapa'], 'Interesado')
        self.assertIsNone(data['agente_id'])  # igual que antes: solo informa agente si hay conversación activa
        r = self.client.post(
            reverse('whatsapp:api_contacto'), data=json.dumps({'phone': '5491100000050', 'etapa': 'no-existe'}),
            content_type='application/json', HTTP_X_API_KEY='k',
        )
        self.assertIn('etapa_error', r.json())


class KanbanTests(Base):
    def setUp(self):
        super().setUp()
        self.mio = Contacto.objects.create(nombre='Mio', telefono='+1', agente=self.a1)
        self.ajeno = Contacto.objects.create(nombre='Ajeno', telefono='+2', agente=self.a2)
        self.contactado = Etapa.objects.get(nombre='Contactado')

    def test_agente_ve_solo_sus_tarjetas(self):
        self.client.force_login(self.a1)
        r = self.client.get(reverse('contacts:kanban'))
        self.assertContains(r, 'Mio')
        self.assertNotContains(r, 'Ajeno')

    def test_supervisor_ve_todo_y_filtra_por_agente(self):
        self.client.force_login(self.sup)
        r = self.client.get(reverse('contacts:kanban'))
        self.assertContains(r, 'Mio')
        self.assertContains(r, 'Ajeno')
        r = self.client.get(reverse('contacts:kanban'), {'agente': self.a2.pk})
        self.assertNotContains(r, '>Mio<')

    def test_mover_tarjeta_propia_registra_historial(self):
        self.client.force_login(self.a1)
        r = self.client.post(reverse('contacts:cambiar_etapa', args=[self.mio.pk]), {'etapa_id': self.contactado.pk})
        self.assertTrue(r.json()['ok'])
        self.mio.refresh_from_db()
        self.assertEqual(self.mio.etapa, self.contactado)
        h = HistorialContacto.objects.get(contacto=self.mio, tipo='etapa')
        self.assertEqual((h.valor_anterior, h.valor_nuevo, h.usuario), ('Nuevo', 'Contactado', self.a1))

    def test_no_puede_mover_tarjeta_ajena(self):
        self.client.force_login(self.a1)
        r = self.client.post(reverse('contacts:cambiar_etapa', args=[self.ajeno.pk]), {'etapa_id': self.contactado.pk})
        self.assertEqual(r.status_code, 403)

    def test_cargar_mas_pagina_la_columna(self):
        for i in range(60):
            Contacto.objects.create(nombre=f'C{i}', telefono=f'+9{i}', agente=self.a1)
        self.client.force_login(self.a1)
        nuevo = Etapa.objects.get(nombre='Nuevo')
        r = self.client.get(reverse('contacts:kanban'))
        self.assertContains(r, 'Cargar más')
        r = self.client.get(reverse('contacts:kanban_columna'), {'etapa': nuevo.pk, 'offset': 50})
        self.assertEqual(r.json()['cantidad'], 11)

    def test_contactos_viejos_sin_etapa_aparecen_en_su_columna(self):
        Contacto.objects.filter(pk=self.mio.pk).update(etapa=None)
        self.client.force_login(self.a1)
        r = self.client.get(reverse('contacts:kanban'))
        self.assertContains(r, 'Sin etapa')


class EtapasAdminTests(Base):
    def test_solo_admin(self):
        self.client.force_login(self.sup)
        self.assertEqual(self.client.get(reverse('contacts:etapas')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('contacts:etapas')).status_code, 200)

    def test_crear_reordenar_y_eliminar_moviendo_contactos(self):
        self.client.force_login(self.admin)
        url = reverse('contacts:etapas')
        self.client.post(url, {'accion': 'crear', 'nombre': 'Demo', 'color': '#123456', 'tipo': 'abierta'})
        demo = Etapa.objects.get(nombre='Demo')
        self.assertEqual(Etapa.objects.last(), demo)
        self.client.post(url, {'accion': 'subir', 'etapa_id': demo.pk})
        self.assertEqual(list(Etapa.objects.values_list('nombre', flat=True))[-2], 'Demo')

        c = Contacto.objects.create(nombre='X', telefono='+1', agente=self.a1, etapa=demo)
        nuevo = Etapa.objects.get(nombre='Nuevo')
        self.client.post(url, {'accion': 'eliminar', 'etapa_id': demo.pk})  # sin destino: no borra
        self.assertTrue(Etapa.objects.filter(pk=demo.pk).exists())
        self.client.post(url, {'accion': 'eliminar', 'etapa_id': demo.pk, 'mover_a': nuevo.pk})
        self.assertFalse(Etapa.objects.filter(pk=demo.pk).exists())
        c.refresh_from_db()
        self.assertEqual(c.etapa, nuevo)

    def test_pagina_respeta_el_orden(self):
        Contacto.objects.create(nombre='X', telefono='+1', agente=self.a1, etapa=Etapa.objects.get(nombre='Perdido'))
        self.client.force_login(self.admin)
        html = self.client.get(reverse('contacts:etapas')).content.decode()
        posiciones = [html.index(f'value="{n}"') for n in Etapa.objects.values_list('nombre', flat=True)]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_color_invalido_se_descarta(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('contacts:etapas'), {'accion': 'crear', 'nombre': 'Z', 'color': 'red;x:y', 'tipo': 'abierta'})
        self.assertEqual(Etapa.objects.get(nombre='Z').color, '#3b82f6')


class ComandoTests(Base):
    def test_diagnostica_y_aplica(self):
        huerfano = Contacto.objects.create(nombre='H', telefono='+1')
        desfasado = Contacto.objects.create(nombre='D', telefono='+2', agente=self.a1)
        Conversacion.objects.create(telefono='+2', contacto=desfasado, agente=self.a2)
        suelta = Conversacion.objects.create(telefono='+3')

        out = StringIO()
        call_command('asignar_sin_agente', stdout=out)
        self.assertIn('Modo diagnóstico', out.getvalue())
        huerfano.refresh_from_db()
        self.assertIsNone(huerfano.agente)

        call_command('asignar_sin_agente', '--aplicar', stdout=StringIO())
        huerfano.refresh_from_db()
        desfasado.refresh_from_db()
        suelta.refresh_from_db()
        self.assertIsNotNone(huerfano.agente)
        self.assertEqual(desfasado.agente, self.a2)  # manda el agente de la conversación
        self.assertIsNotNone(suelta.agente)


class ArchivadoTests(Base):
    def setUp(self):
        from apps.contacts.models import MotivoArchivo
        super().setUp()
        self.motivo = MotivoArchivo.objects.get(nombre='No responde')
        self.interesado = Etapa.objects.get(nombre='Interesado')
        self.c = Contacto.objects.create(nombre='Juan', telefono='+5491100000100', agente=self.a1, etapa=self.interesado)
        self.conv = Conversacion.objects.create(telefono=self.c.telefono, contacto=self.c, agente=self.a1)

    def test_migracion_crea_motivos_y_archiva_contactos_con_conversacion_archivada(self):
        from importlib import import_module
        from apps.contacts.models import MotivoArchivo
        self.assertTrue(MotivoArchivo.objects.filter(nombre='Otro').exists())
        otro = Contacto.objects.create(nombre='Viejo', telefono='+2', agente=self.a1)
        Conversacion.objects.create(telefono='+2', contacto=otro, agente=self.a1, archivada=True)
        import_module('apps.contacts.migrations.0005_datos_archivado') \
            .archivar_contactos_con_conversacion_archivada(django_apps, None)
        otro.refresh_from_db()
        self.c.refresh_from_db()
        self.assertTrue(otro.archivado)
        self.assertFalse(self.c.archivado)

    def test_archivar_desde_inbox_requiere_motivo_y_archiva_contacto(self):
        self.client.force_login(self.a1)
        url = reverse('whatsapp:archivar', args=[self.conv.pk])
        self.assertEqual(self.client.post(url).status_code, 400)
        r = self.client.post(url, {'motivo_id': self.motivo.pk, 'comentario': 'No contesta hace 2 semanas'})
        self.assertTrue(r.json()['ok'])
        self.c.refresh_from_db(); self.conv.refresh_from_db()
        self.assertTrue(self.conv.archivada)
        self.assertTrue(self.c.archivado)
        self.assertEqual(self.c.archivado_motivo, self.motivo)
        self.assertEqual(self.c.archivado_comentario, 'No contesta hace 2 semanas')
        self.assertEqual(self.c.archivado_por, self.a1)
        self.assertEqual(self.c.etapa, self.interesado)  # conserva la etapa
        h = HistorialContacto.objects.get(contacto=self.c, tipo='archivo')
        self.assertEqual((h.valor_nuevo, h.comentario), ('Archivado: No responde', 'No contesta hace 2 semanas'))

    def test_kanban_archivar_y_mover_a_etapa_desarchiva(self):
        self.client.force_login(self.a1)
        self.client.post(reverse('contacts:archivar', args=[self.c.pk]), {'motivo_id': self.motivo.pk})
        r = self.client.get(reverse('contacts:kanban'))
        archivado = next(col for col in r.context['columnas'] if col['key'] == 'archivado')
        self.assertEqual([t.pk for t in archivado['tarjetas']], [self.c.pk])
        interesado = next(col for col in r.context['columnas'] if col['key'] == self.interesado.pk)
        self.assertEqual(interesado['total'], 0)
        self.assertContains(r, 'Antes: Interesado')

        contactado = Etapa.objects.get(nombre='Contactado')
        self.client.post(reverse('contacts:cambiar_etapa', args=[self.c.pk]), {'etapa_id': contactado.pk})
        self.c.refresh_from_db(); self.conv.refresh_from_db()
        self.assertFalse(self.c.archivado)
        self.assertFalse(self.conv.archivada)
        self.assertEqual(self.c.etapa, contactado)

    def test_agente_no_archiva_contacto_ajeno(self):
        self.client.force_login(self.a2)
        r = self.client.post(reverse('contacts:archivar', args=[self.c.pk]), {'motivo_id': self.motivo.pk})
        self.assertEqual(r.status_code, 403)

    def test_si_el_cliente_escribe_se_desarchiva_todo(self):
        from apps.contacts.archivo import archivar
        archivar(conv=self.conv, motivo=self.motivo, usuario=self.a1)
        self.entrante(self.c.telefono)
        self.c.refresh_from_db(); self.conv.refresh_from_db()
        self.assertFalse(self.c.archivado)
        self.assertFalse(self.conv.archivada)
        self.assertEqual(self.c.etapa, self.interesado)
        h = HistorialContacto.objects.filter(contacto=self.c, tipo='archivo').first()
        self.assertEqual((h.valor_nuevo, h.comentario), ('Desarchivado', 'El cliente volvió a escribir'))

    def test_nueva_conversacion_desarchiva(self):
        from apps.contacts.archivo import archivar
        archivar(contacto=self.c, motivo=self.motivo)
        self.client.force_login(self.a1)
        self.client.post(reverse('whatsapp:nueva_conversacion'), {'contacto_id': self.c.pk})
        self.c.refresh_from_db()
        self.assertFalse(self.c.archivado)

    @override_settings(CRM_API_KEY='k')
    def test_api_archivar_con_motivo_y_desarchivar(self):
        url = reverse('whatsapp:api_archivar')
        r = self.client.post(url, data=json.dumps({'phone': self.c.telefono, 'motivo': 'no responde'}),
                             content_type='application/json', HTTP_X_API_KEY='k')
        self.assertTrue(r.json()['ok'])
        self.c.refresh_from_db()
        self.assertTrue(self.c.archivado)
        self.assertEqual(self.c.archivado_motivo, self.motivo)
        self.assertEqual(self.c.archivado_comentario, 'Archivado desde n8n')
        r = self.client.post(url, data=json.dumps({'phone': self.c.telefono, 'motivo': 'inventado'}),
                             content_type='application/json', HTTP_X_API_KEY='k')
        self.assertIn('motivo_error', r.json())
        self.client.post(url, data=json.dumps({'phone': self.c.telefono, 'archivar': False}),
                         content_type='application/json', HTTP_X_API_KEY='k')
        self.c.refresh_from_db()
        self.assertFalse(self.c.archivado)

    def test_ficha_muestra_motivo(self):
        from apps.contacts.archivo import archivar
        archivar(contacto=self.c, motivo=self.motivo, comentario='Dijo que llame en marzo', usuario=self.a1)
        self.client.force_login(self.a1)
        r = self.client.get(reverse('contacts:detail', args=[self.c.pk]))
        self.assertContains(r, 'Archivado: No responde')
        self.assertContains(r, 'Dijo que llame en marzo')
        self.assertContains(r, 'Desarchivar')

    def test_admin_gestiona_motivos(self):
        from apps.contacts.models import MotivoArchivo
        self.client.force_login(self.admin)
        url = reverse('contacts:etapas')
        self.client.post(url, {'accion': 'motivo_crear', 'nombre': 'Precio alto'})
        nuevo = MotivoArchivo.objects.get(nombre='Precio alto')
        self.client.post(url, {'accion': 'motivo_editar', 'motivo_id': nuevo.pk, 'nombre': 'Precio muy alto'})
        nuevo.refresh_from_db()
        self.assertEqual(nuevo.nombre, 'Precio muy alto')
        self.assertFalse(nuevo.activo)
        # en uso: no se puede eliminar
        self.c.archivado_motivo = self.motivo; self.c.save()
        self.client.post(url, {'accion': 'motivo_eliminar', 'motivo_id': self.motivo.pk})
        self.assertTrue(MotivoArchivo.objects.filter(pk=self.motivo.pk).exists())
        self.client.post(url, {'accion': 'motivo_eliminar', 'motivo_id': nuevo.pk})
        self.assertFalse(MotivoArchivo.objects.filter(pk=nuevo.pk).exists())


class EtapaInicialMigracionTests(Base):
    """Los contactos que ya existen y tienen conversación abierta arrancan en la primera etapa."""

    def _migrar(self):
        from importlib import import_module
        import_module('apps.contacts.migrations.0006_etapa_inicial_conversaciones_abiertas') \
            .poner_en_etapa_inicial(django_apps, None)

    def _contacto(self, nombre, telefono, **conv):
        c = Contacto.objects.create(nombre=nombre, telefono=telefono, agente=self.a1)
        if conv:
            Conversacion.objects.create(telefono=telefono, contacto=c, agente=self.a1, **conv)
        Contacto.objects.filter(pk=c.pk).update(etapa=None, etapa_actualizada_at=None)
        return Contacto.objects.get(pk=c.pk)

    def test_solo_los_de_conversacion_abierta_van_a_la_primera_etapa(self):
        abierta = self._contacto('Abierta', '+1', archivada=False)
        archivada = self._contacto('Archivada', '+2', archivada=True)
        sin_conv = self._contacto('Sin conversación', '+3')

        self._migrar()
        for c in (abierta, archivada, sin_conv):
            c.refresh_from_db()
        self.assertEqual(abierta.etapa, Etapa.objects.get(nombre='Nuevo'))
        self.assertIsNotNone(abierta.etapa_actualizada_at)
        self.assertIsNone(archivada.etapa)
        self.assertIsNone(sin_conv.etapa)

    def test_no_pisa_la_etapa_de_quien_ya_tiene_una(self):
        c = self._contacto('Con etapa', '+1', archivada=False)
        interesado = Etapa.objects.get(nombre='Interesado')
        Contacto.objects.filter(pk=c.pk).update(etapa=interesado)
        self._migrar()
        c.refresh_from_db()
        self.assertEqual(c.etapa, interesado)

    def test_no_saca_de_archivado_a_un_contacto_archivado(self):
        from apps.contacts.archivo import archivar
        from apps.contacts.models import MotivoArchivo
        c = self._contacto('Archivado a mano', '+1', archivada=False)
        archivar(contacto=c, motivo=MotivoArchivo.objects.first(), usuario=self.a1)
        Contacto.objects.filter(pk=c.pk).update(etapa=None)
        self._migrar()
        c.refresh_from_db()
        self.assertTrue(c.archivado)
        self.assertIsNone(c.etapa)
