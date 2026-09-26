from django.urls import path
from .views import TelegramWebhookView

app_name = "notifications"

urlpatterns = [
    path("telegram-webhook/", TelegramWebhookView.as_view(), name="telegram-webhook"),
]
