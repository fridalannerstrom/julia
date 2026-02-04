from django.contrib import admin
from .models import PromptSet, Prompt, ActivePromptConfig


@admin.register(PromptSet)
class PromptSetAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    list_filter = ("created_by",)


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ("name", "prompt_set")
    list_filter = ("prompt_set",)
    search_fields = ("name", "text", "prompt_set__name")
    ordering = ("prompt_set__name", "name")


@admin.register(ActivePromptConfig)
class ActivePromptConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "active_set", "updated_at")
