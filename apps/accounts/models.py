from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    STUDENT = "STUDENT", "Student"
    DIRECTOR = "DIRECTOR", "Director"
    HOD = "HOD", "Head of Department"
    ADMIN = "ADMIN", "Admin"


class Department(models.TextChoices):
    CSE = "CSE", "Computer Science & Engineering"
    CST = "CST", "Computer Science & Technology"
    ELECTRICAL = "ELECTRICAL", "Electrical Engineering"
    IT = "IT", "Information Technology"
    MECHANICAL = "MECHANICAL", "Mechanical Engineering"


mobile_validator = RegexValidator(
    regex=r"^\+?\d{10,15}$",
    message="Enter a valid mobile number (10-15 digits, optional leading +).",
)


class User(AbstractUser):
    """
    Custom user model (required from the start per CLAUDE.md).

    Public registration must only ever create STUDENT users - role is never
    settable from a public-facing form. Director/Admin accounts are
    provisioned administratively (Django admin or a management command).
    """

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)

    # Student profile fields (README "Core data model > User")
    roll_number = models.CharField(max_length=32, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    mobile_number = models.CharField(max_length=16, validators=[mobile_validator], blank=True)
    course = models.CharField(max_length=100, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    semester = models.PositiveSmallIntegerField(null=True, blank=True)
    phone_verified = models.BooleanField(default=False)

    # Only meaningful for role=HOD - which department this HOD heads.
    # Every Director-forwarded complaint routes to the HOD whose
    # `department` matches the complaint's `assigned_department`.
    department = models.CharField(
        max_length=20, choices=Department.choices, null=True, blank=True
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["email"], name="unique_user_email"),
        ]
        indexes = [
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return f"{self.full_name or self.username} ({self.role})"

    @property
    def is_student(self):
        return self.role == Role.STUDENT

    @property
    def is_director(self):
        return self.role == Role.DIRECTOR

    @property
    def is_hod(self):
        return self.role == Role.HOD

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN


class OTPPurpose(models.TextChoices):
    """
    Why a code was issued. Codes are always looked up by purpose, so a
    registration code can never be replayed to satisfy a login check (or
    vice versa) even within its validity window.
    """

    LOGIN = "LOGIN", "Student login"
    REGISTRATION = "REGISTRATION", "Account registration"


class OTPChannel(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"


class LoginOTP(models.Model):
    """
    One-time verification code for Students - used both for login (Phase 13)
    and to verify a new account at registration. Delivered by email or SMS
    (`channel`); both go through the identical verification path. Only
    students go through this; Director/HOD/Admin log in directly.

    Safe-storage rule: only a salted hash of the code is ever persisted -
    never the plaintext code (CLAUDE.md: "never log OTP values" extends to
    "never store them in the clear" here).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_otps")
    purpose = models.CharField(max_length=20, choices=OTPPurpose.choices, default=OTPPurpose.LOGIN)
    channel = models.CharField(max_length=10, choices=OTPChannel.choices, default=OTPChannel.EMAIL)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "purpose", "consumed"]),
        ]

    def __str__(self):
        return f"OTP({self.purpose}/{self.channel}) for user {self.user_id}"

    def is_still_usable(self, max_attempts: int) -> bool:
        return (not self.consumed) and timezone.now() < self.expires_at and self.attempts < max_attempts
