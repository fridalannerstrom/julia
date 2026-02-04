from django.db import models
import uuid
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import models


User = get_user_model()

class PromptSet(models.Model):
    name = models.CharField(max_length=120, unique=True)  # "Veronika", "Frida"
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="prompt_sets",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Prompt(models.Model):
    prompt_set = models.ForeignKey(
        PromptSet,
        on_delete=models.CASCADE,
        related_name="prompts",
    )
    name = models.CharField(max_length=100)
    text = models.TextField()

    class Meta:
        unique_together = ("prompt_set", "name")

    def __str__(self):
        return f"{self.name} ({self.prompt_set})"

class ActivePromptConfig(models.Model):
    """
    Singleton: vi använder alltid id=1.
    Denna styr vilket set som är aktivt GLOBALT för alla användare.
    """
    active_set = models.ForeignKey(
        PromptSet,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Active: {self.active_set or 'None'}"

    
    # --- CHAT MODELS -------------------------------------------------------------
from django.conf import settings
from django.db import models

class ChatSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, default="Ny chatt")

    # lägg till dessa två
    flow = models.CharField(max_length=50, blank=True, null=True)  # t.ex. "domarnamnden"
    step = models.PositiveSmallIntegerField(blank=True, null=True) # 1–10

    system_prompt = models.TextField(
        default=(
            "Du är en hjälpsam, saklig och diplomatisk assistent. "
            "Skriv tydligt och konkret, mild tonalitet, inga överdrifter."
        )
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.id})"


class ChatMessage(models.Model):
    ROLE_CHOICES = (("system","system"),("user","user"),("assistant","assistant"))
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}..."


def upload_to_chat(instance, filename):
    return f"chat_uploads/s{instance.message.session_id}/{filename}"

class ChatAttachment(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=upload_to_chat)
    original_name = models.CharField(max_length=255)
    text_excerpt = models.TextField(blank=True)  # endast ren text här

    def __str__(self):
        return self.original_name
    

class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    current_step = models.PositiveIntegerField(default=1)
    data = models.JSONField(default=dict, blank=True)  # hela wizard-state

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Report {self.id}"