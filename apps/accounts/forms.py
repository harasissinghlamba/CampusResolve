from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.complaints.widgets import bootstrapify

from .models import Role, User


def _reclaimable_unverified(**lookup):
    """
    An account that was registered but never OTP-verified is a placeholder,
    not a real account. After REGISTRATION_UNVERIFIED_TTL_HOURS it stops
    blocking that email/roll number so a genuine student isn't locked out
    forever by someone else's abandoned (or malicious) signup attempt.

    Returns the reclaimable User, or None.
    """
    cutoff = timezone.now() - timedelta(hours=settings.REGISTRATION_UNVERIFIED_TTL_HOURS)
    return User.objects.filter(is_active=False, date_joined__lt=cutoff, **lookup).first()


class StudentRegistrationForm(forms.ModelForm):
    """
    Public registration form. Deliberately excludes `role`, `is_staff`,
    `is_superuser`, and any permission field - registration ALWAYS creates a
    STUDENT (CLAUDE.md rule #2 / Phase 2 acceptance: self-promotion impossible).

    save() creates the user with is_active=False. The account only becomes
    usable once the emailed/texted OTP is verified (see accounts.views).
    Django's ModelBackend refuses to authenticate is_active=False users, so
    an unverified signup cannot log in even if the password is correct -
    the verification gate is enforced by Django itself, not just our views.
    """

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, min_length=8)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, min_length=8)

    class Meta:
        model = User
        fields = [
            "full_name",
            "roll_number",
            "email",
            "mobile_number",
            "course",
            "branch",
            "semester",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        existing = User.objects.filter(email=email).first()
        if existing:
            if existing.is_active:
                raise ValidationError("An account with this email already exists.")
            if not _reclaimable_unverified(email=email):
                raise ValidationError(
                    "This email already has a registration awaiting verification. "
                    "Check your inbox for the code, or try again later."
                )
        return email

    def clean_roll_number(self):
        roll_number = self.cleaned_data["roll_number"].strip()
        existing = User.objects.filter(roll_number=roll_number).first()
        if existing:
            if existing.is_active:
                raise ValidationError("An account with this roll number already exists.")
            if not _reclaimable_unverified(roll_number=roll_number):
                raise ValidationError(
                    "This roll number already has a registration awaiting verification. "
                    "Check your inbox for the code, or try again later."
                )
        return roll_number

    def clean_password1(self):
        # Run Django's configured AUTH_PASSWORD_VALIDATORS (length, common
        # passwords, all-numeric, similarity to other fields) rather than
        # relying on min_length alone.
        password = self.cleaned_data["password1"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        # Clear out any stale unverified placeholder occupying this email or
        # roll number - clean_* above already confirmed it's reclaimable.
        User.objects.filter(is_active=False).filter(
            Q(email=self.cleaned_data["email"]) | Q(roll_number=self.cleaned_data["roll_number"])
        ).delete()

        user = super().save(commit=False)
        # Role is hard-coded server-side; never read from form input.
        user.role = Role.STUDENT
        user.username = user.email
        user.is_staff = False
        user.is_superuser = False
        # Not usable until the OTP is verified. Django's ModelBackend blocks
        # login for is_active=False, so this is the actual security gate.
        user.is_active = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    """
    Unverified accounts (is_active=False) are rejected here automatically:
    Django's ModelBackend.authenticate() calls user_can_authenticate() and
    returns None for inactive users, so the form reports the standard
    "please enter a correct email and password" error.

    That generic message is deliberate - distinguishing "wrong password"
    from "account exists but unverified" would leak which emails are
    registered. The registration page handles the recovery path instead
    (re-registering an unverified email re-sends a fresh code).
    """

    username = forms.EmailField(label="Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class OTPVerifyForm(forms.Form):
    code = forms.CharField(
        label="Verification code",
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": True}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        length = settings.OTP_LENGTH
        self.fields["code"].min_length = length
        self.fields["code"].max_length = length
        self.fields["code"].label = f"{length}-digit code"
        self.fields["code"].widget.attrs["maxlength"] = length
        bootstrapify(self)

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise ValidationError(f"Enter the {settings.OTP_LENGTH}-digit numeric code.")
        return code
