from django.db import models

# Create your models here.
class Prompt(models.Model):
    name = models.CharField(max_length=100, unique=True)  # t.ex. "testanalys"
    text = models.TextField()

    def __str__(self):
        return self.name