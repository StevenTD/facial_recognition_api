import os
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.conf import settings

class BaseModelWithAudit(models.Model):
    """Abstract base model with audit fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="%(class)s_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="%(class)s_updated"
    )

    class Meta:
        abstract = True

class CustomUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username must be set')
        user = self.model(username=username, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(username, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin, BaseModelWithAudit):
    """Custom User model for the system."""
    username = models.CharField(max_length=150, unique=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    objects = CustomUserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.username

class Face(BaseModelWithAudit):
    """Model to store biometric data for faces."""
    username = models.CharField(max_length=150, db_index=True)
    face_image = models.ImageField(upload_to='faces/', null=True, blank=True)
    face_encoding = models.BinaryField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="faces"
    )

    def __str__(self):
        return f"Face for {self.username}"

class AttendanceLog(BaseModelWithAudit):
    """Model to store attendance logs."""
    ACTION_CHOICES = [
        ('IN', 'Login'),
        ('OUT', 'Logout'),
    ]
    LOG_TYPE_CHOICES = [
        ("MI", "Morning In"),
        ("MO", "Morning Out"),
        ("AI", "Afternoon In"),
        ("AO", "Afternoon Out"),
    ]
    face = models.ForeignKey(
        Face, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="attendance_logs"
    )
    username = models.CharField(max_length=150, db_index=True) # To record the username at the time of log
    action = models.CharField(max_length=3, choices=ACTION_CHOICES)
    log_type = models.CharField(
        max_length=2, 
        choices=LOG_TYPE_CHOICES,
        null=True, 
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    captured_image = models.ImageField(upload_to='attendance/', null=True, blank=True)

    def __str__(self):
        return f"{self.username} - {self.action} at {self.timestamp}"


class WebhookConfig(models.Model):
    """
    Configurable outbound webhook fired after a successful attendance log.
    Add one entry per external system you want to notify.
    """
    METHOD_CHOICES = [
        ('POST', 'POST'),
        ('GET', 'GET'),
    ]

    name = models.CharField(max_length=100, help_text="Friendly label, e.g. 'HRIS System'")
    url = models.URLField(help_text="Endpoint to call when the hook fires")
    method = models.CharField(max_length=4, choices=METHOD_CHOICES, default='POST')
    log_types = models.CharField(
        max_length=20,
        default='MI,MO,AI,AO',
        help_text="Comma-separated log types that trigger this hook. E.g. 'MI,AO' or 'MI,MO,AI,AO'"
    )
    custom_headers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional JSON object of extra HTTP headers, e.g. {\"Authorization\": \"Bearer token\"}"
    )
    timeout = models.PositiveSmallIntegerField(
        default=5,
        help_text="Request timeout in seconds"
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Webhook Config'
        verbose_name_plural = 'Webhook Configs'

    def __str__(self):
        status = '✓' if self.is_enabled else '✗'
        return f"[{status}] {self.name} → {self.url} ({self.log_types})"
