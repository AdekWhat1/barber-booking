MESSAGES = {
    "past_date": {
        "cs": "Nelze rezervovat termín v minulosti.",
        "uk": "Неможливо забронювати дату в минулому.",
    },
    "no_schedule": {
        "cs": "Pro tento den ještě nebyl nastaven pracovní rozvrh.",
        "uk": "На цей день графік майстра ще не встановлено.",
    },
    "day_off": {
        "cs": "V tento den je zavřeno (volný den).",
        "uk": "Цей день є вихідним.",
    },
    "outside_working_hours": {
        "cs": "Zvolený čas je mimo pracovní dobu ({start} - {end}).",
        "uk": "Обраний час виходить за межі робочих годин ({start} - {end}).",
    },
    "slot_occupied": {
        "cs": "Bohužel, tento termín je již obsazen jiným klientem.",
        "uk": "На жаль, цей час уже зайнятий іншим клієнтом.",
    },
    "missing_params": {
        "cs": 'Parametry "date" a "service_id" jsou povinné.',
        "uk": 'Параметри "date" та "service_id" є обовʼязковими.',
    },
    "invalid_date_format": {
        "cs": "Formát data musí být YYYY-MM-DD.",
        "uk": "Формат дати має бути YYYY-MM-DD.",
    },
    "booking_not_found": {
        "cs": "Rezervace nebyla nalezena.",
        "uk": "Запис не знайдено.",
    },
    "already_cancelled": {
        "cs": "Tato rezervace již byla zrušena.",
        "uk": "Цей запис уже скасовано.",
    },
    "cancel_too_late": {
        "cs": "Rezervaci nelze zrušit online méně než 2 hodiny předem. Kontaktujte prosím kadeřnici telefonicky.",
        "uk": "Скасувати запис онлайн менш ніж за 2 години неможливо. Будь ласка, зателефонуйте майстрині.",
    },
    "cancel_success": {
        "cs": "Vaše rezervace byla úspěšně zrušena.",
        "uk": "Ваш запис успішно скасовано.",
    },
}


def get_msg(key: str, lang: str = "cs", **kwargs) -> str:
    lang = "uk" if lang == "uk" else "cs"
    template = MESSAGES.get(key, {}).get(lang, "")
    return template.format(**kwargs) if kwargs else template
