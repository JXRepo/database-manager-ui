from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import password_validators_help_text_html



class SignUpForm(UserCreationForm):
    """Custom user registration form"""

    username = forms.CharField(
        help_text="No spaces.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Username",
            }
        )
    )

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "Email (optional)",
            }
        ),
    )

    password1 = forms.CharField(
        help_text="At least 8 characters.",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Password",
            }
        ),
    )

    password2 = forms.CharField(
        help_text="Enter the same password again.",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Confirm password",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        """Save the user with the provided email"""
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class SignInForm(AuthenticationForm):
    """Custom user login form"""

    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Username",
            }
        )
    )

    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Password",
            }
        )
    )


class AccountSettingsForm(forms.ModelForm):
    """Update basic account profile fields"""

    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Username",
            }
        )
    )

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "Email (optional)",
            }
        ),
    )

    institution = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Institution (optional)",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        """Populate optional profile fields from the current user profile"""
        super().__init__(*args, **kwargs)

        profile = getattr(self.instance, "profile", None)

        if profile is None:
            return

        self.fields["institution"].initial = profile.institution

    def clean_username(self):
        """Return a unique username for the current account"""
        username = self.cleaned_data["username"].strip()
        duplicate_user = (
            User.objects.filter(username__iexact=username)
            .exclude(pk=self.instance.pk)
            .exists()
        )

        if duplicate_user:
            raise forms.ValidationError("A user with that username already exists.")

        return username

    def clean_institution(self):
        """Return the normalized institution value"""
        return self.cleaned_data.get("institution", "").strip()


class StyledPasswordChangeForm(PasswordChangeForm):
    """Password change form styled for the dashboard UI"""

    def __init__(self, *args, **kwargs):
        """Add Bootstrap classes to password fields"""
        super().__init__(*args, **kwargs)

        placeholders = {
            "old_password": "Current password",
            "new_password1": "New password",
            "new_password2": "Confirm new password",
        }

        for field_name, field in self.fields.items():
            field.widget.attrs.update(
                {
                    "class": "form-control",
                    "placeholder": placeholders.get(field_name, field.label),
                }
            )


class MultipleFileInput(forms.ClearableFileInput):
    """File input that allows selecting multiple files"""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """File field that returns a list of uploaded files"""

    def clean(self, data, initial=None):
        """Clean one or more uploaded files"""
        single_file_clean = super().clean

        if isinstance(data, (list, tuple)):
            return [single_file_clean(file_item, initial) for file_item in data]

        return [single_file_clean(data, initial)]


class JSONUploadForm(forms.Form):
    """
    Upload one or more JSON files

    Attributes
    ----------
    file : UploadedFile
        JSON file or files to upload
    """

    file = MultipleFileField(
        widget=MultipleFileInput(
            attrs={
                "class": "form-control",
                "accept": ".json",
                "multiple": True,
            }
        )
    )
