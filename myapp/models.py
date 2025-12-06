from django.db import models
from django.contrib.auth.models import User

class Prompt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    text = models.TextField()

    class Meta:
        unique_together = ('user', 'name')  # Så varje användare har max 1 av varje prompt-typ

    def __str__(self):
        return f"{self.name} ({self.user.username})"
    
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