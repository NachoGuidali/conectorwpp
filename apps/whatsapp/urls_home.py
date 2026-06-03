from django.urls import path
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

urlpatterns = [
    path('', login_required(lambda r: redirect('whatsapp:inbox')), name='home'),
]
