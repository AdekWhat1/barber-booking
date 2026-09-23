from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    telegram_chat_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name="Telegram Chat ID",
        help_text="ID чату в Telegram для отримання сповіщень про нові записи",
    )

    def __str__(self):
        return self.username
