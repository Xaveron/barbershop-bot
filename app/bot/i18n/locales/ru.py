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
    # --- Админ-панель: общие кнопки (Phase 9F) -------------------------------
    "admin.btn.back": "⬅️ Назад",
    "admin.btn.cancel": "⬅️ Отмена",
    "admin.btn.confirm": "✅ Подтвердить",
    "admin.btn.create": "✅ Создать",
    "admin.btn.delete": "🗑 Удалить",
    "admin.btn.delete_confirm": "🗑 Да, удалить",
    "admin.btn.hide": "🚫 Скрыть",
    "admin.btn.show": "✅ Показать",
    "admin.btn.name": "✏️ Название",
    "admin.btn.description": "📝 Описание",
    "admin.label.branches": "📍 Филиалы",
    # --- Админ-панель: главное меню -------------------------------------------
    "admin.menu.services": "💇 Услуги",
    "admin.menu.barbers": "👨‍💈 Барберы",
    "admin.menu.schedule": "🕐 График",
    "admin.menu.exceptions": "🚫 Исключения",
    "admin.menu.appointments": "📅 Записи",
    "admin.menu.clients": "👥 Клиенты",
    "admin.menu.stats": "📊 Статистика",
    "admin.menu.export": "📥 Экспорт CSV",
    "admin.menu.branches": "📍 Филиалы",
    "admin.menu.staff": "🧑‍💼 Сотрудники",
    "admin.menu.billing": "💳 Тариф",
    "admin.menu.settings": "⚙️ Настройки",
    "admin.menu.my_language": "🌐 Мой язык",
    "admin.menu.back_to_menu": "⬅️ В меню",
    "admin.menu.title": "🛠 <b>Админ-панель</b>\n\nВыберите раздел:",
    # --- Админ-панель: филиалы ------------------------------------------------
    "admin.branches.add": "➕ Добавить филиал",
    "admin.branch.address": "📝 Адрес",
    "admin.branch.back": "⬅️ К филиалам",
    # --- Админ-панель: сотрудники ----------------------------------------------
    "admin.staff.add": "➕ Добавить сотрудника",
    "admin.staff.role": "🔄 Роль",
    "admin.staff.deactivate": "🚫 Деактивировать",
    "admin.staff.deactivate_confirm": "🚫 Да, деактивировать",
    "admin.staff.back": "⬅️ К сотрудникам",
    "admin.role.tenant_owner": "Владелец",
    "admin.role.tenant_admin": "Администратор",
    "admin.role.manager": "Менеджер",
    "admin.role.receptionist": "Ресепшн",
    "admin.role.barber": "Барбер",
    # --- Админ-панель: услуги --------------------------------------------------
    "admin.services.add": "➕ Добавить услугу",
    "admin.service.duration": "⏱ Длительность",
    "admin.service.price": "💰 Цена",
    "admin.service.back": "⬅️ К услугам",
    # --- Админ-панель: барберы --------------------------------------------------
    "admin.barbers.add": "➕ Добавить барбера",
    "admin.barber.name": "✏️ Имя",
    "admin.barber.back": "⬅️ К барберам",
    # --- Админ-панель: график и исключения -------------------------------------
    "admin.schedule.whole_branch": "🏠 Весь филиал",
    "admin.schedule.day_off": "выходной",
    "admin.schedule.set_hours": "✏️ Задать часы",
    "admin.schedule.make_day_off": "🚫 Сделать выходным",
    "admin.exceptions.special_hours": "особые часы",
    "admin.exceptions.add": "➕ Добавить исключение",
    # --- Админ-панель: записи ---------------------------------------------------
    "admin.appointments.cancel_day": "❌ Отменить за день",
    "admin.appointment.reschedule": "🔄 Перенести",
    "admin.appointment.cancel": "❌ Отменить",
    "admin.appointment.no_show": "🚫 Не пришёл",
    "admin.appointment.back": "⬅️ К записям",
    "admin.bulk_cancel.day_row": "{date} — {count} зап.",
    "admin.bulk_cancel.confirm": "❌ Да, отменить {count} зап.",
    # --- Админ-панель: экспорт CSV ----------------------------------------------
    "admin.export.7d": "За 7 дней",
    "admin.export.30d": "За 30 дней",
    "admin.export.90d": "За 90 дней",
    "admin.export.all": "Все записи",
    # --- Админ-панель: настройки арендатора --------------------------------------
    "admin.settings.timezone": "🕐 Часовой пояс",
    "admin.settings.currency": "💰 Валюта",
    "admin.settings.language": "🗣 Язык по умолчанию",
    "admin.settings.title": "⚙️ <b>Настройки арендатора</b>",
    "admin.settings.line_name": "Название: {value}",
    "admin.settings.line_slug": "Слаг: <code>{slug}</code> (неизменяем)",
    "admin.settings.line_timezone": "Часовой пояс: {value}",
    "admin.settings.line_currency": "Валюта: {value}",
    "admin.settings.line_language": "Язык по умолчанию: {value}",
    "admin.settings.line_status": "Статус: {value} (управляется отдельно)",
    "admin.settings.defaults_notice": (
        "⚠️ Часовой пояс, валюта и язык здесь — только дефолт для будущих "
        "филиалов/сотрудников/клиентов. Уже существующие сотрудники, "
        "клиенты и филиалы сохраняют свои собственные значения."
    ),
    "admin.settings.not_found": "Арендатор не найден.",
    "admin.settings.pick_language_prompt": "🗣 Выберите язык по умолчанию для этого арендатора:",
    "admin.settings.unknown_language": "Неизвестный язык.",
    "admin.settings.confirm_change": "Изменить «{field}» на <b>{value}</b>?",
    "admin.settings.field_name": "Название",
    "admin.settings.field_timezone": "Часовой пояс",
    "admin.settings.field_currency": "Валюта",
    "admin.settings.field_language": "Язык по умолчанию",
    "admin.settings.prompt_name": "Отправьте новое название арендатора.",
    "admin.settings.prompt_timezone": (
        "Отправьте часовой пояс в формате IANA, например Europe/Chisinau.\n\n"
        "⚠️ Это только дефолт для НОВЫХ филиалов при их создании — часовые "
        "пояса уже существующих филиалов не изменятся."
    ),
    "admin.settings.prompt_currency": (
        "Отправьте код валюты (3 буквы), например MDL, RON, EUR.\n\n"
        "⚠️ Это только дефолт для НОВЫХ филиалов при их создании — валюта "
        "уже существующих филиалов не изменится."
    ),
    "admin.settings.cancel_hint": "Для отмены: /cancel",
    "admin.errors.session_expired": "Сессия устарела. Откройте /admin заново.",
    "admin.errors.saved": "Сохранено",
    "admin.language.staff_only": "Личный язык доступен только сотрудникам арендатора.",
    "admin.language.pick_prompt": "🌐 Выберите язык интерфейса админ-панели лично для себя:",
    "admin.language.saved_notice": "✅ Язык сохранён лично для вас.",
    "admin.language.unknown_language": "Неизвестный язык.",
    # --- Валидация ввода (Phase 9F) -------------------------------------------
    "validation.field_name_default": "Название",
    "validation.name_too_short": "{field} слишком короткое (минимум 2 символа).",
    "validation.name_too_long": "{field} слишком длинное (максимум {max} символов).",
    "validation.description_too_long": "Описание длиннее {max} символов.",
    "validation.duration_format": "Длительность указывается целым числом минут, например: 45",
    "validation.duration_range": "Длительность должна быть от {min} до {max} минут.",
    "validation.duration_step": "Длительность должна быть кратна 5 минутам.",
    "validation.price_format": "Цена указывается числом, например: 250 или 250.50",
    "validation.price_negative": "Цена не может быть отрицательной.",
    "validation.price_too_high": "Цена не может превышать {max}.",
    "validation.phone_invalid": "Некорректный номер телефона.",
    "validation.time_range_format": "Формат рабочих часов: 10:00-19:00",
    "validation.time_range_invalid": "Некорректное время. Часы 0-23, минуты 0-59.",
    "validation.time_range_order": "Начало рабочего дня должно быть раньше конца.",
    "validation.date_format": "Формат даты: ДД.ММ.ГГГГ, например 25.12.2026",
    "validation.date_past": "Дата уже прошла — укажите сегодняшний день или позже.",
    "validation.date_too_far": "Дата слишком далеко: максимум {max} дней вперёд.",
    "validation.positive_int": "{field} должно быть положительным целым числом.",
    "validation.telegram_id_not_a_number": (
        "Telegram ID — это число (узнать у @userinfobot), а не имя."
    ),
    "validation.telegram_id_invalid": "Некорректный Telegram ID.",
    "validation.timezone_invalid": (
        "Некорректный часовой пояс. Укажите IANA-идентификатор, "
        "например Europe/Chisinau или Europe/Bucharest."
    ),
    "validation.currency_invalid": "Валюта — трёхбуквенный код, например MDL, RON или EUR.",
    "validation.language_invalid": "Язык должен быть одним из {languages}.",
    # --- Админ: общее (Phase 9F) -----------------------------------------------
    "admin.common.cancel_hint": "Для отмены: /cancel",
    "admin.common.status_updated": "Статус обновлён",
    "admin.common.edit_field_prompt": "✏️ {name}\n\n{prompt}\n\n{cancel_hint}",
    # --- Админ: филиалы (продолжение, Phase 9F) ---------------------------------
    "admin.branch.status_active": "активен",
    "admin.branch.status_hidden": "скрыт",
    "admin.branch.card_status": "👁 Статус: {status}",
    "admin.branch.not_found": "Филиал не найден.",
    "admin.branch.add_title": (
        "➕ <b>Новый филиал</b>\n\nШаг 1/2. Отправьте название филиала.\nДля отмены: /cancel"
    ),
    "admin.branch.add_step2": "Шаг 2/2. Адрес филиала (или «-», чтобы пропустить)",
    "admin.branch.create_failed": "⚠️ Не удалось создать филиал.",
    "admin.branch.created": "✅ Филиал создан.\n\n",
    "admin.branch.prompt_name": "Отправьте новое название филиала.",
    "admin.branch.prompt_address": "Отправьте новый адрес (или «-», чтобы очистить).",
    "admin.branches.empty": "📍 Филиалов пока нет. Добавьте первый.",
    "admin.branches.list_title": "📍 <b>Филиалы</b> (всего {total})",
    # --- Админ: универсальное редактирование поля (Phase 9F) ---------------------
    "admin.editing.session_expired": "Сессия редактирования устарела. Откройте /admin заново.",
    "admin.editing.unknown_field": "Неизвестное поле.",
    "admin.editing.save_failed": "⚠️ Не удалось сохранить: возможно, значение конфликтует с другим.",
    "admin.editing.saved": "✅ Сохранено\n\n",
    "admin.service.not_found": "Услуга не найдена.",
    "admin.barber.not_found": "Барбер не найден.",
    # --- Админ: услуги (Phase 9F) -------------------------------------------------
    "admin.service.status_active": "активна",
    "admin.service.status_hidden": "скрыта",
    "admin.service.card": (
        "💇 <b>{name}</b>\n\n"
        "💰 Цена: {price}\n"
        "⏱ Длительность: {duration}\n"
        "📝 Описание: {description}\n"
        "👁 Статус: {status}"
    ),
    "admin.service.branches_prompt": (
        "📍 <b>{name}</b>\n\nДоступность по филиалам (нажмите, чтобы переключить):"
    ),
    "admin.service.availability_failed": "Не удалось изменить доступность.",
    "admin.service.add_title": (
        "➕ <b>Новая услуга</b>\n\nШаг 1/4. Отправьте название услуги.\nДля отмены: /cancel"
    ),
    "admin.service.add_step2": "Шаг 2/4. Длительность в минутах (кратно 5), например: 45",
    "admin.service.add_step3": "Шаг 3/4. Цена, например: 250",
    "admin.service.add_step4": "Шаг 4/4. Описание (или «-», чтобы пропустить)",
    "admin.service.create_failed": (
        "⚠️ Не удалось создать услугу. Возможно, такое название уже есть."
    ),
    "admin.service.created": "✅ Услуга создана\n\n",
    "admin.service.prompt_name": "Отправьте новое название услуги.",
    "admin.service.prompt_duration": "Отправьте новую длительность в минутах (кратно 5).",
    "admin.service.prompt_price": "Отправьте новую цену, например: 300",
    "admin.service.prompt_description": "Отправьте новое описание (или «-», чтобы очистить).",
    "admin.service.delete_confirm": (
        "🗑 Удалить услугу «{name}»?\n\n"
        "Если по услуге есть активные записи, удаление будет заблокировано — "
        "используйте «Скрыть»."
    ),
    "admin.service.delete_blocked": "По услуге есть активные записи — можно только скрыть её.",
    "admin.service.delete_failed": "Не удалось удалить: услуга используется в истории записей.",
    "admin.service.deleted": "🗑 Услуга удалена\n\n",
    "admin.services.empty": "💇 Услуг пока нет. Добавьте первую.",
    "admin.services.list_title": "💇 <b>Услуги</b> (всего {total})",
    "admin.common.deleted_toast": "Удалено",
    # --- Админ: барберы (Phase 9F) -------------------------------------------------
    "admin.barber.schedule_not_set": "не задан",
    "admin.barber.card": (
        "👨‍💈 <b>{name}</b>\n\n📝 {description}\n👁 Статус: {status}\n🕐 График: {days}"
    ),
    "admin.barber.branches_prompt": (
        "📍 <b>{name}</b>\n\nФилиалы (нажмите, чтобы привязать/отвязать):"
    ),
    "admin.barber.cannot_unassign_last_branch": (
        "Нельзя убрать последний филиал — барбера будет невозможно записать "
        "или задать ему график. Сначала привяжите другой филиал."
    ),
    "admin.barber.assign_failed": "Не удалось привязать филиал.",
    "admin.barber.add_title": (
        "➕ <b>Новый барбер</b>\n\nШаг 1/2. Отправьте имя барбера.\nДля отмены: /cancel"
    ),
    "admin.barber.add_step2": "Шаг 2/2. Короткое описание (или «-», чтобы пропустить)",
    "admin.barber.create_failed": "⚠️ Не удалось создать барбера.",
    "admin.barber.created": "✅ Барбер создан. Не забудьте задать график работы.\n\n",
    "admin.barber.prompt_name": "Отправьте новое имя барбера.",
    "admin.barber.prompt_description": "Отправьте новое описание (или «-», чтобы очистить).",
    "admin.barber.delete_confirm": (
        "🗑 Удалить барбера «{name}»?\n\n"
        "При наличии активных записей удаление блокируется — используйте «Скрыть»."
    ),
    "admin.barber.delete_blocked": "У барбера есть активные записи — можно только скрыть его.",
    "admin.barber.delete_failed": "Не удалось удалить: барбер используется в истории записей.",
    "admin.barber.deleted": "🗑 Барбер удалён\n\n",
    "admin.barbers.empty": "👨‍💈 Барберов пока нет. Добавьте первого.",
    "admin.barbers.list_title": "👨‍💈 <b>Барберы</b> (всего {total})",
    "admin.barber.field_name": "Имя",
    # --- Админ: сотрудники (Phase 9F) -------------------------------------------
    "admin.staff.empty": "🧑‍💼 Сотрудников пока нет.",
    "admin.staff.list_title": "🧑‍💼 <b>Сотрудники</b> (всего {total})",
    "admin.staff.not_found": "Сотрудник не найден.",
    "admin.staff.card_title": "🧑‍💼 <b>{telegram_id}</b>",
    "admin.staff.card_role": "Роль: {role}",
    "admin.staff.card_status": "Статус: {status}",
    "admin.staff.branches_hint": "Филиалы (нажмите, чтобы привязать/отвязать):",
    "admin.staff.all_branches_hint": "Эта роль имеет доступ ко всем филиалам арендатора.",
    "admin.staff.cannot_unassign_last_branch": (
        "Нельзя убрать последний филиал — у сотрудника не останется доступа. "
        "Сначала привяжите другой филиал."
    ),
    "admin.staff.assign_failed": "Не удалось привязать филиал.",
    "admin.staff.add_title": (
        "➕ <b>Новый сотрудник</b>\n\n"
        "Отправьте Telegram ID сотрудника (узнать у @userinfobot).\n\n"
        "Для отмены: /cancel"
    ),
    "admin.staff.pick_role_prompt": "Выберите роль:",
    "admin.staff.create_confirm": (
        "Создать сотрудника <code>{telegram_id}</code> с ролью <b>{role}</b>?"
    ),
    "admin.staff.telegram_id_taken": "Этот Telegram ID уже привязан к сотруднику.",
    "admin.staff.limit_reached": "Достигнут лимит сотрудников по тарифу.",
    "admin.staff.create_failed": "Не удалось создать сотрудника.",
    "admin.staff.added_toast": "Сотрудник добавлен",
    "admin.staff.role_pick_title": "🔄 <b>{telegram_id}</b>\n\nВыберите новую роль:",
    "admin.staff.role_change_confirm": (
        "Изменить роль <code>{telegram_id}</code> на <b>{role}</b>?"
    ),
    "admin.staff.role_or_target_invalid": "Сотрудник не найден или роль некорректна.",
    "admin.staff.sole_owner_protected": "Нельзя — это единственный активный владелец арендатора.",
    "admin.staff.role_changed_toast": "Роль изменена",
    "admin.staff.deactivate_confirm_prompt": "🚫 Деактивировать <code>{telegram_id}</code>?",
    "admin.staff.already_deactivated": "Сотрудник уже деактивирован.",
    "admin.staff.actor_unknown": "Не удалось определить инициатора.",
    "admin.staff.deactivated_toast": "Деактивирован",
    # --- Админ: график и исключения (продолжение, Phase 9F) ---------------------
    "admin.schedule.add_barber_first": "Сначала добавьте барбера.",
    "admin.schedule.title_pick_barber": "🕐 <b>График работы</b>\n\nВыберите барбера:",
    "admin.schedule.pick_branch_title": "🕐 <b>{barber}</b>\n\nВыберите филиал:",
    "admin.schedule.no_accessible_branches": "Нет доступных вам филиалов для этого барбера.",
    "admin.schedule.week_title": "🕐 <b>График: {barber}</b> — 📍{branch}",
    "admin.schedule.pick_day_prompt": "Выберите день недели для изменения:",
    "admin.schedule.weekday_title": "🕐 <b>{barber} — {weekday}</b>\n\nСейчас: {current}",
    "admin.schedule.invalid_data": "Некорректные данные.",
    "admin.schedule.set_hours_prompt": (
        "Отправьте рабочие часы на {weekday} в формате 10:00-19:00\n\nДля отмены: /cancel"
    ),
    "admin.schedule.save_failed": "⚠️ Не удалось сохранить график.",
    "admin.schedule.hours_saved": "✅ {weekday}: {start}-{end}",
    "admin.schedule.day_off_saved": "✅ {weekday} теперь выходной.",
    "admin.schedule.title_exceptions": "🚫 <b>Исключения из графика</b>",
    "admin.schedule.no_exceptions": "Пока нет запланированных исключений.",
    "admin.schedule.exc_scope_whole_branch": "весь филиал",
    "admin.schedule.exc_scope_barber_fallback": "барбер",
    "admin.schedule.exc_row": "• {date} — {scope}: {detail}",
    "admin.schedule.exc_tap_hint": "Нажмите на исключение, чтобы удалить его.",
    "admin.schedule.new_exception_title": "🚫 <b>Новое исключение</b>\n\nДля кого?",
    "admin.schedule.invalid_choice": "Некорректный выбор.",
    "admin.schedule.no_accessible_branches_generic": "Нет доступных вам филиалов.",
    "admin.schedule.pick_branch_generic": "Выберите филиал:",
    "admin.schedule.ask_date_prompt": (
        "Отправьте дату в формате ДД.ММ.ГГГГ, например 31.12.2026\n\nДля отмены: /cancel"
    ),
    "admin.schedule.barber_not_at_branch": "Барбер не работает в этом филиале.",
    "admin.schedule.date_mode_prompt": "Дата: {date}\n\nЧто делаем?",
    "admin.schedule.mode_off": "🚫 Выходной",
    "admin.schedule.mode_hours": "🕐 Особые часы",
    "admin.schedule.ask_hours_prompt": (
        "Отправьте особые часы работы в формате 12:00-16:00\n\nДля отмены: /cancel"
    ),
    "admin.schedule.exception_save_failed": "Не удалось сохранить исключение.",
    "admin.schedule.exception_saved": "✅ Исключение сохранено.",
    "admin.schedule.exception_saved_hours": "✅ Исключение сохранено: {start}-{end}",
    "admin.schedule.exception_not_found": "Исключение не найдено.",
    # --- Админ: записи (продолжение, Phase 9F) ---------------------------------
    "admin.appointments.empty": "📅 Предстоящих записей нет.",
    "admin.appointments.list_title": (
        "📅 <b>Предстоящие записи</b> (всего {total})\n\nВыберите запись:"
    ),
    "admin.appointment.not_found": "Запись не найдена.",
    "admin.appointment.invalid": "Некорректная запись.",
    "admin.appointment.cancelled_by_admin_title": "❌ <b>Запись отменена администратором</b>\n\n",
    "admin.appointment.cancelled_toast": "Отменено",
    "admin.appointment.no_show_title": "🚫 <b>Отмечено: клиент не пришёл</b>\n\n",
    "admin.appointment.no_show_toast": "Отмечено",
    "admin.bulk_cancel.no_appointments_in_branch": "📅 Нет предстоящих записей в «{branch}».",
    "admin.bulk_cancel.pick_date_prompt": "❌ <b>Массовая отмена за день</b>\n\nВыберите дату:",
    "admin.bulk_cancel.no_accessible_branches": "📅 Нет доступных вам филиалов.",
    "admin.bulk_cancel.pick_branch_prompt": "❌ <b>Массовая отмена за день</b>\n\nВыберите филиал:",
    "admin.bulk_cancel.invalid_date": "Некорректная дата.",
    "admin.bulk_cancel.no_active_appointments": "На этот день нет активных записей.",
    "admin.bulk_cancel.confirm_title": (
        "❌ <b>Подтвердите отмену</b>\n\n"
        "Филиал: <b>{branch}</b>\n"
        "Дата: <b>{date}</b>\n"
        "Записей: <b>{count}</b>\n\n"
        "Каждый клиент получит уведомление об отмене."
    ),
    "admin.bulk_cancel.done_title": (
        "✅ <b>Отменено {count} записей на {date}</b> — 📍{branch}\n\n"
        "Отправляем уведомления клиентам..."
    ),
    "admin.bulk_cancel.done_toast": "Отменено: {count}",
    # --- Админ: статистика, клиенты, экспорт (Phase 9F) -------------------------
    "admin.stats.title": "📊 <b>Статистика</b>",
    "admin.stats.total_appointments": "📅 Всего записей: <b>{value}</b>",
    "admin.stats.upcoming": "⏭ Предстоящих: <b>{value}</b>",
    "admin.stats.today": "📆 Сегодня: <b>{value}</b>",
    "admin.stats.this_month": "🗓 В этом месяце: <b>{value}</b>",
    "admin.stats.cancelled_month": "🚫 Отменено за месяц: <b>{value}</b>",
    "admin.stats.clients": "👥 Клиентов: <b>{value}</b>",
    "admin.stats.revenue_today": "💰 Выручка сегодня: <b>{value}</b>",
    "admin.stats.revenue_month": "💰 Выручка за месяц: <b>{value}</b>",
    "admin.stats.top_services_header": "🔥 <b>Популярные услуги (месяц)</b>",
    "admin.stats.top_barbers_header": "👨‍💈 <b>Барберы (месяц)</b>",
    "admin.clients.empty": "👥 Клиентов пока нет.",
    "admin.clients.list_title": "👥 <b>Клиенты</b> (всего {total})",
    "admin.clients.row": "• {name} — {count} зап.{blocked}\n  {telegram_id}",
    "admin.export.title": "📥 <b>Экспорт записей в CSV</b>\n\nВыберите период:",
    "admin.export.no_rights": "Недостаточно прав для экспорта.",
    "admin.export.period_all": "все записи",
    "admin.export.period_days": "за {days} дн.",
    "admin.export.invalid_period": "Некорректный период.",
    "admin.export.caption": "📥 Экспорт записей ({label})",
    "admin.export.sent_toast": "Файл отправлен",
    "admin.errors.no_rights_or_branch_unavailable": "Недостаточно прав или филиал недоступен.",
}
