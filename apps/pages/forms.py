from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import password_validators_help_text_html



class SignUpForm(UserCreationForm):
    """Custom user registration form"""

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

    password1 = forms.CharField(
        help_text="Use at least 8 characters with letters and numbers.",
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
