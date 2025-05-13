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