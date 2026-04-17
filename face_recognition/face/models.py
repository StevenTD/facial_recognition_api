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
    face = models.ForeignKey(
        Face, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="attendance_logs"
    )
    username = models.CharField(max_length=150) # To record the username at the time of log
    action = models.CharField(max_length=3, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    captured_image = models.ImageField(upload_to='attendance/', null=True, blank=True)

    def __str__(self):
        return f"{self.username} - {self.action} at {self.timestamp}"
