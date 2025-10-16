from django.urls import path
from .views import index, prompt_editor
from django.contrib.auth import views as auth_views
from . import views


urlpatterns = [
    path('', index, name='index'),
    path("prompts/", prompt_editor, name="prompt_editor"),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("chat/", views.chat_home, name="chat_home"),
    path("chat/<int:session_id>/", views.chat_session, name="chat_session"),
    path("chat/<int:session_id>/send/", views.chat_send, name="chat_send"),
    path("chat/<int:session_id>/delete/", views.chat_delete, name="chat_delete"),
]