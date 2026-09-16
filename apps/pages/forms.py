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

    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        label="Remember me",
        widget=forms.CheckboxInput(
            attrs={
                "class": "form-check-input input-primary",
                "aria-describedby": "remember-me-help",
            }
        ),
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

    def save(self, commit=True):
        """
        Save profile fields without overwriting concurrently changed credentials

        Parameters
        ----------
        commit : bool, optional
            Whether to persist the updated profile fields immediately.

        Returns
        -------
        User
            The existing account with its edited username and email.
        """
        user = super().save(commit=False)
        if commit:
            user.save(update_fields=["username", "email"])
        return user


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


class ORCIDAccountSetupForm(UserCreationForm):
    """
    Set local credentials on the existing ORCID account
    """

    class Meta(UserCreationForm.Meta):
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        """
        Style credential fields and preserve Django's model validators

        Parameters
        ----------
        *args : tuple
            Positional form arguments.
        **kwargs : dict
            Form data and the existing user instance.
        """
        super().__init__(*args, **kwargs)
        self.fields["username"].strip = False
        self.fields["username"].help_text = "No spaces."
        self.fields["password1"].help_text = "At least 8 characters."
        placeholders = {
            "username": "Username",
            "password1": "Password",
            "password2": "Confirm password",
        }

        for field_name, field in self.fields.items():
            field.widget.attrs.update(
                {"class": "form-control", "placeholder": placeholders[field_name]}
            )

    def clean_username(self):
        """
        Allow the current username while rejecting names held by another account

        Returns
        -------
        str
            Username normalized by Django's username field.

        Raises
        ------
        forms.ValidationError
            Another account already uses the chosen username.
        """
        username = self.cleaned_data["username"]
        duplicate_user = (
            User.objects.filter(username__iexact=username)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicate_user:
            raise forms.ValidationError(
                self.instance.unique_error_message(User, ["username"])
            )
        return username


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
