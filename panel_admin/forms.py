from django import forms
from accounts.models import CustomUser

_INPUT = 'glass-input'
_INPUT_STYLE = 'width:100%;padding:10px 14px;border-radius:10px;font-size:0.875rem;'
_SELECT_STYLE = 'width:100%;padding:10px 14px;border-radius:10px;font-size:0.875rem;cursor:pointer;'


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': _INPUT,
            'style': _INPUT_STYLE,
            'placeholder': '••••••••',
        }),
        label='Contraseña'
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'role', 'daily_prompt_limit', 'is_unlimited_prompts', 'is_active',
            'can_view_videoprompt', 'can_view_fanpages', 'can_view_extractor', 'can_view_stats', 'can_view_dashboard', 'can_manage_api_keys', 'can_manage_users'
        ]
        widgets = {
            'username': forms.TextInput(attrs={
                'class': _INPUT,
                'style': _INPUT_STYLE,
                'placeholder': 'Nombre de usuario',
            }),
            'role': forms.Select(attrs={
                'class': _INPUT,
                'style': _SELECT_STYLE,
            }),
            'daily_prompt_limit': forms.NumberInput(attrs={
                'class': _INPUT,
                'style': _INPUT_STYLE,
                'min': '0',
                'placeholder': '10',
            }),
            'is_unlimited_prompts': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'is_active': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_videoprompt': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_fanpages': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_extractor': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_stats': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_dashboard': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_manage_api_keys': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_manage_users': forms.CheckboxInput(attrs={'style': 'display:none;'}),
        }
        labels = {
            'username': 'Username',
            'role': 'Rol',
            'daily_prompt_limit': 'Cuota Diaria de Prompts',
            'is_unlimited_prompts': 'Cuota Ilimitada',
            'is_active': 'Activo',
            'can_view_videoprompt': 'Acceso a Video to Prompt',
            'can_view_fanpages': 'Acceso a Fanpage Creator',
            'can_view_extractor': 'Acceso a Fan Extractor',
            'can_view_stats': 'Acceso a Stats del Reel',
            'can_view_dashboard': 'Acceso al Dashboard',
            'can_manage_api_keys': 'Gestionar Pool de Claves IA',
            'can_manage_users': 'Administrar Usuarios',
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username


class UserEditForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            'username', 'role', 'daily_prompt_limit', 'is_unlimited_prompts', 'is_active',
            'can_view_videoprompt', 'can_view_fanpages', 'can_view_extractor', 'can_view_stats', 'can_view_dashboard', 'can_manage_api_keys', 'can_manage_users'
        ]
        widgets = {
            'username': forms.TextInput(attrs={
                'class': _INPUT,
                'style': _INPUT_STYLE,
            }),
            'role': forms.Select(attrs={
                'class': _INPUT,
                'style': _SELECT_STYLE,
            }),
            'daily_prompt_limit': forms.NumberInput(attrs={
                'class': _INPUT,
                'style': _INPUT_STYLE,
                'min': '0',
            }),
            'is_unlimited_prompts': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'is_active': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_videoprompt': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_fanpages': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_extractor': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_stats': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_view_dashboard': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_manage_api_keys': forms.CheckboxInput(attrs={'style': 'display:none;'}),
            'can_manage_users': forms.CheckboxInput(attrs={'style': 'display:none;'}),
        }
        labels = {
            'username': 'Username',
            'role': 'Rol',
            'daily_prompt_limit': 'Cuota Diaria de Prompts',
            'is_unlimited_prompts': 'Cuota Ilimitada',
            'is_active': 'Activo',
            'can_view_videoprompt': 'Acceso a Video to Prompt',
            'can_view_fanpages': 'Acceso a Fanpage Creator',
            'can_view_extractor': 'Acceso a Fan Extractor',
            'can_view_stats': 'Acceso a Stats del Reel',
            'can_view_dashboard': 'Acceso al Dashboard',
            'can_manage_api_keys': 'Gestionar Pool de Claves IA',
            'can_manage_users': 'Administrar Usuarios',
        }
