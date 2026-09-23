from django import forms
from .models import WordPressSite


class WordPressSiteForm(forms.ModelForm):
    test_connection_on_save = forms.BooleanField(
        required=False,
        initial=True,
        label='Probar conexión inmediatamente al guardar',
        help_text='Verifica de inmediato el acceso a la API REST de WordPress.'
    )

    class Meta:
        model = WordPressSite
        fields = ['name', 'site_url', 'username', 'application_password', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'shadcn-input',
                'placeholder': 'ej: Blog Oficial de Tecnología',
                'autocomplete': 'off',
            }),
            'site_url': forms.URLInput(attrs={
                'class': 'shadcn-input',
                'placeholder': 'https://misitio.com',
                'autocomplete': 'off',
            }),
            'username': forms.TextInput(attrs={
                'class': 'shadcn-input',
                'placeholder': 'ej: editor_wp o admin',
                'autocomplete': 'off',
            }),
            'application_password': forms.PasswordInput(
                render_value=True,
                attrs={
                    'class': 'shadcn-input',
                    'placeholder': 'xxxx xxxx xxxx xxxx',
                    'autocomplete': 'new-password',
                }
            ),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'w-4 h-4 rounded text-red-600 focus:ring-red-500 border-zinc-700 bg-zinc-900 cursor-pointer',
            }),
        }

    def clean_site_url(self):
        url = self.cleaned_data.get('site_url', '').strip()
        if url:
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            url = url.rstrip('/')
        return url

    def clean_application_password(self):
        password = self.cleaned_data.get('application_password', '')
        if password:
            password = password.replace(' ', '').strip()
        return password
