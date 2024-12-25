from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db import models
from django.utils import timezone
from django.conf import settings
from accounts.managers import CustomUserManager
import warnings


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    profile_pic = models.ImageField(blank=True, upload_to='profile_pics')

    boards = GenericRelation(
        'boards.Board', object_id_field='owner_id', content_type_field='owner_model')
    starred_boards = models.ManyToManyField('boards.Board', blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    def can_view_board(self, board):
        ProjectMembership = apps.get_model('projects', 'ProjectMembership')

        if board.owner_model == ContentType.objects.get(model='project'):
            try:
                pmem = ProjectMembership.objects.get(
                    member=self, project__id=board.owner_id)
            except ProjectMembership.DoesNotExist:
                return False
        else:
            if board.owner_id != self.id:
                return False
        return True

    def __str__(self):
        return self.email


class OTP(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        # Get the OTP expiration time from settings or set a default value
        expiration_time = getattr(settings, 'OTP_EXPIRATION_TIME', None)

        # If the setting is not declared, raise a warning and set a default time
        if expiration_time is None:
            expiration_time = 300  # default to 5 minutes
            warnings.warn(
                "OTP_EXPIRATION_TIME is not set in settings. Using default value of 5 minutes.",
                UserWarning
            )

        return (timezone.now() - self.created_at).seconds < expiration_time
