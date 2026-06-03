from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import User


class AdminRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_admin:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Solo administradores.')
        return super().dispatch(request, *args, **kwargs)


class UserListView(AdminRequiredMixin, View):
    template_name = 'users/list.html'

    def get(self, request):
        users = User.objects.all().order_by('rol', 'username')
        return render(request, self.template_name, {'users': users})


class UserCreateView(AdminRequiredMixin, View):
    template_name = 'users/form.html'

    def get(self, request):
        return render(request, self.template_name, {'rol_choices': User.ROL_CHOICES})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        rol = request.POST.get('rol', User.ROL_AGENTE)
        telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, 'Usuario y contraseña son requeridos.')
            return render(request, self.template_name, {'rol_choices': User.ROL_CHOICES, 'data': request.POST})

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Ese nombre de usuario ya existe.')
            return render(request, self.template_name, {'rol_choices': User.ROL_CHOICES, 'data': request.POST})

        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name,
            rol=rol, telefono=telefono,
        )
        messages.success(request, f'Usuario {user.username} creado.')
        return redirect('users:list')


class UserUpdateView(AdminRequiredMixin, View):
    template_name = 'users/form.html'

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, {'obj': user, 'rol_choices': User.ROL_CHOICES})

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        user.email = request.POST.get('email', '').strip()
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.rol = request.POST.get('rol', user.rol)
        user.telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '').strip()
        if password:
            user.set_password(password)
        user.save()
        messages.success(request, 'Usuario actualizado.')
        return redirect('users:list')


class UserToggleView(AdminRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            return JsonResponse({'ok': False, 'error': 'No podés desactivarte a vos mismo.'})
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        return JsonResponse({'ok': True, 'is_active': user.is_active})
