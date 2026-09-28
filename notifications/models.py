from django.db import models


class TelegramAdmin(models.Model):
    chat_id = models.CharField(
        max_length=64, unique=True, verbose_name="Telegram Chat ID"
    )
    username = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Username"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Адміністратор Telegram"
        verbose_name_plural = "Адміністратори Telegram"

    def __str__(self):
        return f"{self.username or 'Admin'} ({self.chat_id})"
