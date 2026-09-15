"""Русская локаль."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # --- Кнопки -------------------------------------------------------------
    "btn.book": "💈 Записаться",
    "btn.my": "📅 Мои записи",
    "btn.services": "💇 Услуги",
    "btn.barbers": "👨‍💈 Барберы",
    "btn.contacts": "📍 Контакты",
    "btn.faq": "❓ FAQ",
    "btn.language": "🌐 Язык",
    "btn.admin": "🛠 Админ-панель",
    "btn.back": "⬅️ Назад",
    "btn.back_to_menu": "⬅️ В меню",
    "btn.back_to_my": "⬅️ К моим записям",
    "btn.confirm": "✅ Подтвердить",
    "btn.cancel": "❌ Отмена",
    "btn.reschedule": "🔄 Перенести",
    "btn.cancel_appointment": "❌ Отменить",
    "btn.cancel_yes": "✅ Да, отменить",
    "btn.share_phone": "📱 Отправить номер",
    "btn.skip": "Пропустить",
    "btn.open_map": "Открыть на карте",
    # --- Общее --------------------------------------------------------------
    "common.greeting": (
        "💈 <b>{shop}</b>\n\n"
        "Привет, {name}! Здесь можно записаться на стрижку за пару касаний, "
        "посмотреть свои записи и найти нас на карте.\n\n"
        "Выберите действие:"
    ),
    "common.main_menu": "Главное меню. Выберите действие:",
    "common.help": (
        "<b>Как пользоваться ботом</b>\n\n"
        "💈 <b>Записаться</b> — услуга, барбер, дата, время.\n"
        "📅 <b>Мои записи</b> — перенос и отмена.\n"
        "💇 <b>Услуги</b> — прайс и длительность.\n"
        "👨‍💈 <b>Барберы</b> — наши мастера.\n"
        "📍 <b>Контакты</b> — адрес и график.\n"
        "❓ <b>FAQ</b> — частые вопросы.\n\n"
        "Команды: /start — меню, /language — язык, /cancel — сбросить действие."
    ),
    "common.action_cancelled": "Действие отменено.",
    "common.error_alert": "Произошла ошибка. Попробуйте ещё раз.",
    "common.error_message": "Произошла ошибка. Попробуйте ещё раз или наберите /start.",
    "common.outdated_button": "Кнопка устарела. Откройте меню командой /start.",
    "common.unknown_message": "Не понял команду. Воспользуйтесь меню ниже 👇",
    "common.admin_only": "Эта команда доступна только администратору.",
    "common.no_rights": "Недостаточно прав.",
    "common.private_only": "Я работаю только в личных сообщениях. Напишите мне в личку: /start",
    "common.too_fast": "Слишком часто, подождите секунду.",
    "common.too_many_messages": "Слишком много сообщений подряд. Подождите немного.",
    # --- Язык ---------------------------------------------------------------
    "language.choose": "🌐 Выберите язык:",
    "language.saved": "Готово! Язык интерфейса: {language}",
    # --- Запись -------------------------------------------------------------
    "booking.step_branch": "Выберите филиал:",
    "booking.branch_gone": "Этот филиал больше недоступен.",
    "booking.step_service": "Шаг 1 из 4 — выберите услугу:",
    "booking.step_barber": "Шаг 2 из 4 — выберите барбера:",
    "booking.step_day": "Шаг 3 из 4 — выберите дату:",
    "booking.step_time": "Шаг 4 из 4 — выберите время:",
    "booking.no_services": "Пока нет доступных услуг. Загляните позже.",
    "booking.no_barbers": "Сейчас нет доступных барберов. Загляните позже.",
    "booking.no_days": (
        "У барбера {barber} нет свободных дат в ближайшие {days} дней.\n\n"
        "Попробуйте выбрать другого барбера."
    ),
    "booking.no_slots": "На эту дату свободных слотов уже не осталось.",
    "booking.service_gone": "Услуга больше недоступна.",
    "booking.barber_gone": "Барбер больше не принимает записи.",
    "booking.bad_date": "Некорректная дата.",
    "booking.bad_time": "Некорректное время.",
    "booking.slot_taken": "Это время только что заняли. Выберите другое.",
    "booking.check_details": "Проверьте детали записи:",
    "booking.confirmed_title": "✅ <b>Запись подтверждена!</b>",
    "booking.reminder_note": "Мы напомним о визите за 24 часа и за 2 часа.",
    "booking.done": "Готово!",
    "booking.declined": "Запись отменена. Возвращаемся в меню.",
    "booking.session_expired": "Сессия записи устарела, начнём сначала.",
    "booking.ask_phone": (
        "📱 Оставьте номер телефона — барбершоп свяжется с вами, если планы изменятся.\n\n"
        "Нажмите кнопку ниже или отправьте номер сообщением."
    ),
    "booking.phone_saved": "Спасибо! Номер сохранён.",
    "booking.phone_invalid": "Не похоже на номер телефона. Попробуйте ещё раз или пропустите шаг.",
    "booking.phone_skipped": "Хорошо, продолжим без номера.",
    # --- Мои записи ---------------------------------------------------------
    "appointments.empty": (
        "У вас пока нет активных записей.\n\nНажмите «💈 Записаться», чтобы выбрать время."
    ),
    "appointments.title": "📅 <b>Ваши записи</b> ({count}):\n\nВыберите запись для управления.",
    "appointments.not_found": "Запись не найдена.",
    "appointments.invalid": "Некорректная запись.",
    "appointments.cancel_question": "Отменить эту запись?",
    "appointments.cancelled_title": "❌ <b>Запись отменена</b>",
    "appointments.cancelled_toast": "Запись отменена",
    "appointments.no_days_to_move": (
        "У барбера нет свободных дат для переноса. "
        "Попробуйте позже или отмените запись и создайте новую."
    ),
    "appointments.move_title": "🔄 <b>Перенос записи</b>\n\nТекущее время:",
    "appointments.move_choose_day": "Выберите новую дату:",
    "appointments.move_choose_time": "🔄 <b>Перенос записи</b>\n\n📅 {day}\nВыберите новое время:",
    "appointments.move_summary": "Перенести запись на:",
    "appointments.moved_title": "🔄 <b>Запись перенесена</b>",
    "appointments.move_session_expired": "Сессия переноса устарела.",
    "appointments.no_slots_for_day": "На эту дату слотов не осталось.",
    "appointments.move_cancelled": "Перенос отменён",
    "appointments.moved_by_shop": "🔄 <b>Барбершоп перенёс вашу запись</b>",
    "appointments.questions": "Вопросы: {phone}",
    "appointments.cancelled_by_shop": "❌ <b>Барбершоп отменил вашу запись</b>",
    "appointments.apologies": "Приносим извинения. Свяжитесь с нами: {phone}",
    # --- Инфо ---------------------------------------------------------------
    "info.services_title": "💇 <b>Услуги и цены</b>",
    "info.services_empty": "Список услуг пока пуст.",
    "info.barbers_title": "👨‍💈 <b>Наши барберы</b>",
    "info.barbers_empty": "Список барберов пока пуст.",
    "info.schedule_title": "🕐 <b>График работы</b>",
    "info.schedule_unknown": "График уточняется",
    "info.day_off": "выходной",
    # --- FAQ ----------------------------------------------------------------
    "faq.title": "❓ <b>Частые вопросы</b>",
    "faq.q1": "Нужно ли приходить заранее?",
    "faq.a1": "Достаточно прийти за 5 минут до начала — так мастер начнёт вовремя.",
    "faq.q2": "Что если я опоздаю?",
    "faq.a2": (
        "Опоздание больше чем на 10 минут может сократить услугу или потребовать переноса: "
        "после вас записан другой клиент."
    ),
    "faq.q3": "Как отменить или перенести запись?",
    "faq.a3": (
        "Откройте «📅 Мои записи» и выберите нужное действие. "
        "Это доступно не позднее чем за {cancel_lead} минут до начала."
    ),
    "faq.q4": "Можно ли записаться без предоплаты?",
    "faq.a4": "Да, запись бесплатная. Оплата — на месте наличными или картой.",
    "faq.q5": "Сколько записей можно держать одновременно?",
    "faq.a5": "До {max_active} активных записей на один аккаунт.",
    "faq.q6": "За сколько дней открыта запись?",
    "faq.a6": "На {horizon} дней вперёд.",
    # --- Статусы ------------------------------------------------------------
    "status.confirmed": "✅ Подтверждена",
    "status.cancelled": "❌ Отменена",
    "status.completed": "☑️ Завершена",
    "status.no_show": "🚫 Клиент не пришёл",
    # --- Уведомления --------------------------------------------------------
    "notify.reminder_24h": "⏰ <b>Напоминание: вы записаны завтра</b>",
    "notify.reminder_2h": "⏰ <b>Напоминание: ваша запись через 2 часа</b>",
    "notify.new_appointment": "🆕 <b>Новая запись</b>",
    "notify.cancelled_by_client": "🚫 <b>Запись отменена клиентом</b>",
    "notify.cancelled_by_admin": "🚫 <b>Запись отменена администратором</b>",
    "notify.client_moved": "🔄 <b>Клиент перенёс запись</b>",
    "notify.return_reminder": (
        "💈 <b>Пора к барберу?</b>\n\n"
        "Прошло {weeks} нед. с вашего последнего визита в {shop}.\n"
        "Самое время записаться снова!\n\n"
        "Нажмите /start, чтобы выбрать удобное время."
    ),
    # --- Доменные ошибки ----------------------------------------------------
    "rule.already_cancelled": "Эта запись уже отменена.",
    "rule.already_completed": "Эта запись уже завершена.",
    "rule.already_started": "Время записи уже наступило.",
    "rule.cancel_deadline": (
        "Отменить запись можно не позднее чем за {minutes} минут до начала. "
        "Пожалуйста, свяжитесь с барбершопом по телефону."
    ),
    "rule.reschedule_deadline": (
        "Перенести запись можно не позднее чем за {minutes} минут до начала."
    ),
    "rule.limit_reached": (
        "У вас уже {count} активных записей — это максимум. "
        "Отмените одну из них, чтобы записаться снова."
    ),
    "error.service_unavailable": "Услуга больше недоступна. Выберите другую.",
    "error.barber_unavailable": "Барбер больше не принимает записи. Выберите другого.",
    "error.barber_not_at_branch": "Барбер не работает в этом филиале. Выберите другого.",
    "error.branch_unavailable": "Этот филиал больше недоступен. Выберите другой.",
    "error.service_not_at_branch": "Эта услуга недоступна в выбранном филиале.",
    "error.barber_not_provide_service": "Барбер не предоставляет эту услугу. Выберите другого.",
    "error.slot_busy": "Это время уже занято. Пожалуйста, выберите другое.",
    "error.slot_race": "Кто-то успел занять это время секундой раньше. Выберите другой слот.",
    "error.create_failed": "Не удалось создать запись. Попробуйте ещё раз.",
    "error.move_failed": "Не удалось перенести запись. Попробуйте ещё раз.",
    "error.appointment_not_found": "Запись не найдена.",
    "error.barber_locked": (
        "Сейчас кто-то оформляет запись к этому мастеру. Попробуйте ещё раз через минуту."
    ),
    # --- Онбординг арендатора -------------------------------------------------
    "onboarding.not_active_customer": (
        "🚧 Этот барбершоп ещё настраивается и пока не принимает записи. "
        "Загляните чуть позже!"
    ),
    "onboarding.owner_claimed": "👋 Вы назначены владельцем этого барбершопа.",
    "onboarding.welcome": (
        "🏪 <b>Настройка барбершопа</b>\n\n"
        "Давайте настроим ваш барбершоп за несколько шагов: филиал, услуги, "
        "барберы и график работы. Прогресс сохраняется — можно продолжить в любой момент."
    ),
    "onboarding.step_business_name": "Шаг 1. Как называется ваш барбершоп?",
    "onboarding.step_branch_name": "Шаг 2. Название первого филиала (например, «Центр»).",
    "onboarding.step_branch_timezone": (
        "Часовой пояс филиала — IANA-идентификатор, например Europe/Chisinau "
        "или Europe/Bucharest.\n\nТекущее значение по умолчанию: {default}. "
        "Отправьте своё значение или «-», чтобы оставить это."
    ),
    "onboarding.step_branch_currency": (
        "Валюта филиала — трёхбуквенный код, например MDL, RON или EUR.\n\n"
        "По умолчанию: {default}. Отправьте свой код или «-», чтобы оставить это."
    ),
    "onboarding.step_service_name": "Шаг 3. Название первой услуги (например, «Стрижка»).",
    "onboarding.step_service_duration": "Длительность услуги в минутах, например: 45",
    "onboarding.step_service_price": "Цена услуги, например: 250",
    "onboarding.step_barber_name": "Шаг 4. Имя первого барбера.",
    "onboarding.step_schedule_hours": (
        "Шаг 5. Рабочие часы барбера на каждый день недели, "
        "в формате 10:00-19:00."
    ),
    "onboarding.invalid_timezone": (
        "Некорректный часовой пояс. Укажите IANA-идентификатор, "
        "например Europe/Chisinau."
    ),
    "onboarding.invalid_currency": "Некорректная валюта. Трёхбуквенный код, например MDL.",
    "onboarding.invalid_name": "Название слишком короткое или длинное (2-120 символов).",
    "onboarding.invalid_duration": "Длительность — целое число минут от 5 до 480, кратное 5.",
    "onboarding.invalid_price": "Цена указывается числом, например: 250 или 250.50",
    "onboarding.invalid_hours": "Формат рабочих часов: 10:00-19:00",
    "onboarding.review_title": "📋 <b>Проверка перед запуском</b>",
    "onboarding.review_ready": "✅ Всё готово! Можно запускать барбершоп.",
    "onboarding.review_not_ready": "Ещё не готово к запуску:",
    "onboarding.missing_branch": "— нет ни одного активного филиала",
    "onboarding.missing_service": "— нет ни одной активной услуги",
    "onboarding.missing_barber": "— нет ни одного барбера, привязанного к филиалу",
    "onboarding.missing_schedule": "— у барбера не задан рабочий график",
    "onboarding.btn_activate": "🚀 Запустить барбершоп",
    "onboarding.btn_continue": "➡️ Продолжить настройку",
    "onboarding.activated": (
        "🎉 Барбершоп запущен! Теперь клиенты могут записываться, "
        "а вам доступна полная админ-панель (/admin)."
    ),
    "onboarding.activation_blocked": (
        "Пока нельзя запустить — сначала завершите настройку (см. список выше)."
    ),
    # --- Биллинг (Phase 6) ---------------------------------------------------
    "billing.limit_reached": "Достигнут лимит тарифа «{limit_name}»: {current}/{maximum}.",
    "billing.feature_not_available": "Функция «{feature_name}» недоступна на вашем тарифе.",
    "billing.subscription_inactive": "Подписка неактивна. Обратитесь к владельцу барбершопа.",
    "billing.try_again": "Не удалось обработать запрос, попробуйте ещё раз.",
    "billing.limit.max_branches": "Филиалы",
    "billing.limit.max_barbers": "Барберы",
    "billing.limit.max_staff": "Сотрудники",
    "billing.limit.max_services": "Услуги",
    "billing.limit.max_monthly_appointments": "Записи в месяц",
    "billing.feature.basic_booking": "Базовое бронирование",
    "billing.feature.reminders": "Напоминания",
    "billing.feature.csv_export": "Экспорт в CSV",
    "billing.feature.analytics": "Аналитика",
    "billing.status.trialing": "Пробный период",
    "billing.status.active": "Активна",
    "billing.status.past_due": "Просрочена",
    "billing.status.canceled": "Отменена",
    "billing.status.expired": "Истекла",
    "billing.screen_title": "💳 Тариф",
    "billing.current_plan": "Тариф: <b>{plan_name}</b>",
    "billing.subscription_status": "Статус подписки: {status}",
    "billing.features_header": "Функции:",
    "billing.limits_header": "Лимиты:",
    "billing.limit_line": "{limit_name}: {current}/{maximum}",
    "billing.limit_line_unlimited": "{limit_name}: {current}/∞",
    "billing.feature_line_on": "✅ {feature_name}",
    "billing.feature_line_off": "🚫 {feature_name}",
    "billing.dev_change_plan_btn": "🔧 [dev] Сменить тариф: {plan_name}",
    "billing.plan_changed": "Тариф изменён на «{plan_name}».",
}
