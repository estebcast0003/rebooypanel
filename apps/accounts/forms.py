from django import forms
from django.contrib.auth.forms import PasswordChangeForm

_INPUT = (
    'input input-bordered w-full rounded-xl bg-base-200/50 border-base-300 '
    'text-sm focus:border-primary focus:outline-none transition pr-10'
)


class PasswordChangeCustomForm(PasswordChangeForm):
    revoke_other_sessions = forms.BooleanField(
        required=False,
        initial=True,
        label='Cerrar mis sesiones en otros dispositivos',
        help_text='Por seguridad, cierra la sesión de esta cuenta en otros navegadores y dispositivos.',
        widget=forms.CheckboxInput(attrs={'class': 'toggle toggle-warning toggle-sm'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('old_password', 'new_password1', 'new_password2'):
            field = self.fields.get(field_name)
            if field:
                field.widget.attrs.update({
                    'class': _INPUT,
                    'placeholder': '••••••••',
                    'autocomplete': 'current-password' if field_name == 'old_password' else 'new-password',
                })
