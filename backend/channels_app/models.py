from django.db import models
from django.utils.text import slugify
from accounts.models import CustomUser


class TeamChannel(models.Model):

    CHANNEL_CHOICES = (
        ('operations', 'Operations'),
        ('development', 'Development'),
        ('finance', 'Finance'),
        ('hr', 'Human Resources'),
        ('ai_ml', 'AI/ML'),
        ('qa', 'Quality Analysis'),
        ('surveyor', 'Surveyor'),
        ('management', 'Management'),
        ('business_development', 'Business Development'),
        ('gis', 'GIS'),
    )

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    members = models.ManyToManyField(
        CustomUser,
        related_name='team_channels',
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    profile_pic = models.ImageField(upload_to='channel_pics/', blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @property
    def profile_pic_url(self):
        if self.profile_pic and hasattr(self.profile_pic, 'url'):
            return self.profile_pic.url
        return None

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

