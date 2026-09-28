from django import forms
from accounts.models import CustomUser

_INPUT = 'input input-bordered w-full rounded-xl bg-base-200/50 border-base-300 text-sm focus:border-primary focus:outline-none transition'
_SELECT = 'select select-bordered w-full rounded-xl bg-base-200/50 border-base-300 text-sm focus:border-primary focus:outline-none transition'


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': _INPUT,
            'placeholder': '••••••••',
        }),
        label='Contraseña'
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'role', 'daily_prompt_limit', 'is_unlimited_prompts', 'is_active',
            'can_view_videoprompt', 'can_view_ig_downloader', 'can_view_fanpages', 'can_view_extractor', 'can_view_dashboard', 'can_manage_users'
        ]
        widgets = {
            'username': forms.TextInput(attrs={
                'class': _INPUT,
                'placeholder': 'Nombre de usuario',
            }),
            'role': forms.Select(attrs={
                'class': _SELECT,
            }),
            'daily_prompt_limit': forms.NumberInput(attrs={
                'class': _INPUT,
                'min': '0',
                'placeholder': '10',
            }),
            'is_unlimited_prompts': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'toggle toggle-success toggle-sm'}),
            'can_view_videoprompt': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_ig_downloader': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_fanpages': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_extractor': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_dashboard': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_manage_users': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
        }
        labels = {
            'username': 'Username',
            'role': 'Rol',
            'daily_prompt_limit': 'Cuota Diaria de Prompts',
            'is_unlimited_prompts': 'Cuota Ilimitada',
            'is_active': 'Activo',
            'can_view_videoprompt': 'Acceso a Video to Prompt',
            'can_view_ig_downloader': 'Acceso a IG Downloader',
            'can_view_fanpages': 'Acceso a Fanpage Creator',
            'can_view_extractor': 'Acceso a Fan Extractor',
            'can_view_dashboard': 'Acceso al Dashboard',
            'can_manage_users': 'Administrar Usuarios',
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.can_view_stats = True
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            'username', 'role', 'daily_prompt_limit', 'is_unlimited_prompts', 'is_active',
            'can_view_videoprompt', 'can_view_ig_downloader', 'can_view_fanpages', 'can_view_extractor', 'can_view_dashboard', 'can_manage_users'
        ]
        widgets = {
            'username': forms.TextInput(attrs={
                'class': _INPUT,
            }),
            'role': forms.Select(attrs={
                'class': _SELECT,
            }),
            'daily_prompt_limit': forms.NumberInput(attrs={
                'class': _INPUT,
                'min': '0',
            }),
            'is_unlimited_prompts': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'toggle toggle-success toggle-sm'}),
            'can_view_videoprompt': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_ig_downloader': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_fanpages': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_extractor': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_view_dashboard': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
            'can_manage_users': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary toggle-sm'}),
        }
        labels = {
            'username': 'Username',
            'role': 'Rol',
            'daily_prompt_limit': 'Cuota Diaria de Prompts',
            'is_unlimited_prompts': 'Cuota Ilimitada',
            'is_active': 'Activo',
            'can_view_videoprompt': 'Acceso a Video to Prompt',
            'can_view_ig_downloader': 'Acceso a IG Downloader',
            'can_view_fanpages': 'Acceso a Fanpage Creator',
            'can_view_extractor': 'Acceso a Fan Extractor',
            'can_view_dashboard': 'Acceso al Dashboard',
            'can_manage_users': 'Administrar Usuarios',
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.can_view_stats = True
        if commit:
            user.save()
        return user
