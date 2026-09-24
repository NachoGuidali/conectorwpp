from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import pre_delete
from django.dispatch import receiver


@receiver(user_logged_in)
def agente_entra_en_turno(sender, request, user, **kwargs):
    if user.rol == user.ROL_AGENTE:
        user.en_turno = True
        user.save(update_fields=['en_turno'])


@receiver(user_logged_out)
def agente_sale_de_turno(sender, request, user, **kwargs):
    if user and user.rol == user.ROL_AGENTE:
        user.en_turno = False
        user.save(update_fields=['en_turno'])


@receiver(pre_delete, sender=get_user_model())
def repartir_cartera_antes_de_borrar(sender, instance, **kwargs):
    """Al borrar un usuario, su cartera pasa a otros agentes en vez de quedar sin dueño."""
    from apps.contacts.asignacion import redistribuir_cartera
    redistribuir_cartera(instance)
