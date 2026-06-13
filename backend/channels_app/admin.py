from django.contrib import admin
from .models import TeamChannel


@admin.register(TeamChannel)
class TeamChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    filter_horizontal = ('members',)
