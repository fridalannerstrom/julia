from django.contrib import admin
from .models import Prompt

class PromptAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'short_text')
    search_fields = ('user__username', 'name')
    list_filter = ('user',)

    def short_text(self, obj):
        return (obj.text[:75] + '...') if len(obj.text) > 75 else obj.text
    short_text.short_description = 'Prompttext (förhandsvisning)'

admin.site.register(Prompt, PromptAdmin)