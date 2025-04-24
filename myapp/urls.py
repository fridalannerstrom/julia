from django.urls import path
from .views import index, prompt_editor


urlpatterns = [
    path('', index, name='index'),
    path("prompts/", prompt_editor, name="prompt_editor"),
]