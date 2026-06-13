from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):

    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('management', 'Management'),
        ('employee', 'Employee'),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='employee'
    )

    department = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    last_seen = models.DateTimeField(null=True, blank=True)

    about = models.TextField(blank=True, null=True)

    profile_pic = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def is_admin_user(self):
        return self.role == 'admin'

    def is_management_user(self):
        return self.role == 'management'

    def is_employee_user(self):
        return self.role == 'employee'

    def profile_pic_url(self):
        if self.profile_pic and hasattr(self.profile_pic, 'url'):
            return self.profile_pic.url
        return None