"""English locale (also the fallback for missing keys)."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # --- Buttons ------------------------------------------------------------
    "btn.book": "💈 Book",
    "btn.my": "📅 My bookings",
    "btn.services": "💇 Services",
    "btn.barbers": "👨‍💈 Barbers",
    "btn.contacts": "📍 Contacts",
    "btn.faq": "❓ FAQ",
    "btn.language": "🌐 Language",
    "btn.admin": "🛠 Admin panel",
    "btn.back": "⬅️ Back",
    "btn.back_to_menu": "⬅️ Menu",
    "btn.back_to_my": "⬅️ My bookings",
    "btn.confirm": "✅ Confirm",
    "btn.cancel": "❌ Cancel",
    "btn.reschedule": "🔄 Reschedule",
    "btn.cancel_appointment": "❌ Cancel",
    "btn.cancel_yes": "✅ Yes, cancel",
    "btn.share_phone": "📱 Share number",
    "btn.skip": "Skip",
    "btn.open_map": "Open in maps",
    # --- Common -------------------------------------------------------------
    "common.greeting": (
        "💈 <b>{shop}</b>\n\n"
        "Hi, {name}! Book a haircut in a couple of taps, check your bookings "
        "and find us on the map.\n\n"
        "Choose an action:"
    ),
    "common.main_menu": "Main menu. Choose an action:",
    "common.help": (
        "<b>How to use the bot</b>\n\n"
        "💈 <b>Book</b> — service, barber, date, time.\n"
        "📅 <b>My bookings</b> — reschedule and cancel.\n"
        "💇 <b>Services</b> — prices and duration.\n"
        "👨‍💈 <b>Barbers</b> — our team.\n"
        "📍 <b>Contacts</b> — address and hours.\n"
        "❓ <b>FAQ</b> — frequent questions.\n\n"
        "Commands: /start — menu, /language — language, /cancel — reset the current step."
    ),
    "common.action_cancelled": "Action cancelled.",
    "common.error_alert": "Something went wrong. Please try again.",
    "common.error_message": "Something went wrong. Please try again or send /start.",
    "common.outdated_button": "This button is outdated. Open the menu with /start.",
    "common.unknown_message": "I didn't get that. Use the menu below 👇",
    "common.admin_only": "This command is for the administrator only.",
    "common.no_rights": "Not enough rights.",
    "common.private_only": "I only work in private chats. Message me directly: /start",
    "common.too_fast": "Too fast, please wait a second.",
    "common.too_many_messages": "Too many messages in a row. Please wait a moment.",
    # --- Language -----------------------------------------------------------
    "language.choose": "🌐 Choose your language:",
    "language.saved": "Done! Interface language: {language}",
    # --- Booking ------------------------------------------------------------
    "booking.step_branch": "Choose a location:",
    "booking.branch_gone": "This location is no longer available.",
    "booking.step_service": "Step 1 of 4 — choose a service:",
    "booking.step_barber": "Step 2 of 4 — choose a barber:",
    "booking.step_day": "Step 3 of 4 — choose a date:",
    "booking.step_time": "Step 4 of 4 — choose a time:",
    "booking.no_services": "No services available yet. Please check back later.",
    "booking.no_barbers": "No barbers available right now. Please check back later.",
    "booking.no_days": (
        "{barber} has no free dates in the next {days} days.\n\nTry another barber."
    ),
    "booking.no_slots": "No free slots left for this date.",
    "booking.service_gone": "This service is no longer available.",
    "booking.barber_gone": "This barber no longer takes bookings.",
    "booking.bad_date": "Invalid date.",
    "booking.bad_time": "Invalid time.",
    "booking.slot_taken": "This time has just been taken. Please pick another one.",
    "booking.check_details": "Please check the booking details:",
    "booking.confirmed_title": "✅ <b>Booking confirmed!</b>",
    "booking.reminder_note": "We'll remind you 24 hours and 2 hours before the visit.",
    "booking.done": "Done!",
    "booking.declined": "Booking cancelled. Back to the menu.",
    "booking.session_expired": "The booking session expired, let's start over.",
    "booking.ask_phone": (
        "📱 Share your phone number so the barbershop can reach you if plans change.\n\n"
        "Tap the button below or send the number as a message."
    ),
    "booking.phone_saved": "Thanks! Your number is saved.",
    "booking.phone_invalid": "That doesn't look like a phone number. Try again or skip this step.",
    "booking.phone_skipped": "No problem, we'll continue without a number.",
    # --- My bookings --------------------------------------------------------
    "appointments.empty": "You have no active bookings.\n\nTap «💈 Book» to pick a time.",
    "appointments.title": "📅 <b>Your bookings</b> ({count}):\n\nPick one to manage it.",
    "appointments.not_found": "Booking not found.",
    "appointments.invalid": "Invalid booking.",
    "appointments.cancel_question": "Cancel this booking?",
    "appointments.cancelled_title": "❌ <b>Booking cancelled</b>",
    "appointments.cancelled_toast": "Booking cancelled",
    "appointments.no_days_to_move": (
        "This barber has no free dates to move to. "
        "Try later or cancel the booking and create a new one."
    ),
    "appointments.move_title": "🔄 <b>Reschedule</b>\n\nCurrent time:",
    "appointments.move_choose_day": "Choose a new date:",
    "appointments.move_choose_time": "🔄 <b>Reschedule</b>\n\n📅 {day}\nChoose a new time:",
    "appointments.move_summary": "Move the booking to:",
    "appointments.moved_title": "🔄 <b>Booking moved</b>",
    "appointments.move_session_expired": "The reschedule session expired.",
    "appointments.no_slots_for_day": "No slots left for this date.",
    "appointments.move_cancelled": "Reschedule cancelled",
    "appointments.moved_by_shop": "🔄 <b>The barbershop moved your booking</b>",
    "appointments.questions": "Questions: {phone}",
    "appointments.cancelled_by_shop": "❌ <b>The barbershop cancelled your booking</b>",
    "appointments.apologies": "We're sorry. Please contact us: {phone}",
    # --- Info ---------------------------------------------------------------
    "info.services_title": "💇 <b>Services and prices</b>",
    "info.services_empty": "The service list is empty for now.",
    "info.barbers_title": "👨‍💈 <b>Our barbers</b>",
    "info.barbers_empty": "The barber list is empty for now.",
    "info.schedule_title": "🕐 <b>Opening hours</b>",
    "info.schedule_unknown": "Hours to be announced",
    "info.day_off": "closed",
    # --- FAQ ----------------------------------------------------------------
    "faq.title": "❓ <b>Frequently asked questions</b>",
    "faq.q1": "Should I arrive early?",
    "faq.a1": "Five minutes before the slot is enough — that way your barber starts on time.",
    "faq.q2": "What if I'm late?",
    "faq.a2": (
        "Being more than 10 minutes late may shorten the service or require rescheduling: "
        "another client is booked right after you."
    ),
    "faq.q3": "How do I cancel or reschedule?",
    "faq.a3": (
        "Open «📅 My bookings» and pick the action. "
        "It's available up to {cancel_lead} minutes before the start."
    ),
    "faq.q4": "Can I book without prepayment?",
    "faq.a4": "Yes, booking is free. You pay on site, by cash or card.",
    "faq.q5": "How many bookings can I have at once?",
    "faq.a5": "Up to {max_active} active bookings per account.",
    "faq.q6": "How far ahead can I book?",
    "faq.a6": "{horizon} days ahead.",
    # --- Statuses -----------------------------------------------------------
    "status.confirmed": "✅ Confirmed",
    "status.cancelled": "❌ Cancelled",
    "status.completed": "☑️ Completed",
    "status.no_show": "🚫 No-show",
    # --- Notifications ------------------------------------------------------
    "notify.reminder_24h": "⏰ <b>Reminder: your visit is tomorrow</b>",
    "notify.reminder_2h": "⏰ <b>Reminder: your visit is in 2 hours</b>",
    "notify.new_appointment": "🆕 <b>New booking</b>",
    "notify.cancelled_by_client": "🚫 <b>Booking cancelled by the client</b>",
    "notify.cancelled_by_admin": "🚫 <b>Booking cancelled by the administrator</b>",
    "notify.client_moved": "🔄 <b>The client moved a booking</b>",
    "notify.return_reminder": (
        "💈 <b>Time for a haircut?</b>\n\n"
        "It's been {weeks} weeks since your last visit to {shop}.\n"
        "How about booking again?\n\n"
        "Tap /start to pick a convenient time."
    ),
    # --- Domain errors ------------------------------------------------------
    "rule.already_cancelled": "This booking is already cancelled.",
    "rule.already_completed": "This booking is already completed.",
    "rule.already_started": "The booking time has already started.",
    "rule.cancel_deadline": (
        "You can cancel up to {minutes} minutes before the start. "
        "Please call the barbershop instead."
    ),
    "rule.reschedule_deadline": (
        "You can reschedule up to {minutes} minutes before the start."
    ),
    "rule.limit_reached": (
        "You already have {count} active bookings — that's the maximum. "
        "Cancel one to book again."
    ),
    "error.service_unavailable": "This service is no longer available. Please pick another one.",
    "error.barber_unavailable": "This barber no longer takes bookings. Please pick another one.",
    "error.barber_not_at_branch": (
        "This barber doesn't work at this location. Please pick another one."
    ),
    "error.branch_unavailable": "This location is no longer available. Please pick another one.",
    "error.service_not_at_branch": "This service isn't available at the selected location.",
    "error.barber_not_provide_service": (
        "This barber doesn't offer this service. Please pick another one."
    ),
    "error.slot_busy": "This time is already taken. Please pick another one.",
    "error.slot_race": "Someone took this slot a second earlier. Please pick another one.",
    "error.create_failed": "Could not create the booking. Please try again.",
    "error.move_failed": "Could not move the booking. Please try again.",
    "error.appointment_not_found": "Booking not found.",
    "error.barber_locked": (
        "Someone is booking this barber right now. Please try again in a minute."
    ),
    # --- Tenant onboarding ----------------------------------------------------
    "onboarding.not_active_customer": (
        "🚧 This barbershop is still being set up and isn't taking bookings yet. "
        "Please check back soon!"
    ),
    "onboarding.owner_claimed": "👋 You've been set as the owner of this barbershop.",
    "onboarding.welcome": (
        "🏪 <b>Barbershop setup</b>\n\n"
        "Let's set up your barbershop in a few steps: location, services, barbers, "
        "and working hours. Progress is saved — you can continue anytime."
    ),
    "onboarding.step_business_name": "Step 1. What's your barbershop called?",
    "onboarding.step_branch_name": "Step 2. Name of your first location (e.g. \"Downtown\").",
    "onboarding.step_branch_timezone": (
        "Location timezone — an IANA identifier, e.g. Europe/Chisinau or "
        "Europe/Bucharest.\n\nCurrent default: {default}. Send your own value or "
        "\"-\" to keep this one."
    ),
    "onboarding.step_branch_currency": (
        "Location currency — a three-letter code, e.g. MDL, RON or EUR.\n\n"
        "Default: {default}. Send your own code or \"-\" to keep this one."
    ),
    "onboarding.step_service_name": "Step 3. Name of your first service (e.g. \"Haircut\").",
    "onboarding.step_service_duration": "Service duration in minutes, e.g.: 45",
    "onboarding.step_service_price": "Service price, e.g.: 250",
    "onboarding.step_barber_name": "Step 4. Name of your first barber.",
    "onboarding.step_schedule_hours": (
        "Step 5. This barber's working hours for every day of the week, "
        "in the format 10:00-19:00."
    ),
    "onboarding.invalid_timezone": (
        "Invalid timezone. Please use an IANA identifier, e.g. Europe/Chisinau."
    ),
    "onboarding.invalid_currency": "Invalid currency. A three-letter code, e.g. MDL.",
    "onboarding.invalid_name": "Name is too short or too long (2-120 characters).",
    "onboarding.invalid_duration": "Duration is a whole number of minutes, 5-480, a multiple of 5.",
    "onboarding.invalid_price": "Price is a number, e.g.: 250 or 250.50",
    "onboarding.invalid_hours": "Working hours format: 10:00-19:00",
    "onboarding.review_title": "📋 <b>Review before launch</b>",
    "onboarding.review_ready": "✅ Everything's ready! You can launch your barbershop.",
    "onboarding.review_not_ready": "Not ready to launch yet:",
    "onboarding.missing_branch": "— no active location yet",
    "onboarding.missing_service": "— no active service yet",
    "onboarding.missing_barber": "— no barber assigned to a location yet",
    "onboarding.missing_schedule": "— this barber has no working hours set",
    "onboarding.btn_activate": "🚀 Launch barbershop",
    "onboarding.btn_continue": "➡️ Continue setup",
    "onboarding.activated": (
        "🎉 Your barbershop is live! Customers can now book, and the full admin "
        "panel is available to you (/admin)."
    ),
    "onboarding.activation_blocked": (
        "Can't launch yet — finish setup first (see the list above)."
    ),
    # --- Billing (Phase 6) ---------------------------------------------------
    "billing.limit_reached": "Plan limit reached for «{limit_name}»: {current}/{maximum}.",
    "billing.feature_not_available": "The «{feature_name}» feature is not available on your plan.",
    "billing.subscription_inactive": "Subscription is inactive. Contact the barbershop owner.",
    "billing.try_again": "Could not process the request, please try again.",
    "billing.limit.max_branches": "Branches",
    "billing.limit.max_barbers": "Barbers",
    "billing.limit.max_staff": "Staff",
    "billing.limit.max_services": "Services",
    "billing.limit.max_monthly_appointments": "Appointments per month",
    "billing.feature.basic_booking": "Basic booking",
    "billing.feature.reminders": "Reminders",
    "billing.feature.csv_export": "CSV export",
    "billing.feature.analytics": "Analytics",
    "billing.status.trialing": "Trial",
    "billing.status.active": "Active",
    "billing.status.past_due": "Past due",
    "billing.status.canceled": "Canceled",
    "billing.status.expired": "Expired",
    "billing.screen_title": "💳 Plan",
    "billing.current_plan": "Plan: <b>{plan_name}</b>",
    "billing.subscription_status": "Subscription status: {status}",
    "billing.features_header": "Features:",
    "billing.limits_header": "Limits:",
    "billing.limit_line": "{limit_name}: {current}/{maximum}",
    "billing.limit_line_unlimited": "{limit_name}: {current}/∞",
    "billing.feature_line_on": "✅ {feature_name}",
    "billing.feature_line_off": "🚫 {feature_name}",
    "billing.dev_change_plan_btn": "🔧 [dev] Change plan: {plan_name}",
    "billing.plan_changed": "Plan changed to «{plan_name}».",
    # --- Admin panel: common buttons (Phase 9F) -------------------------------
    "admin.btn.back": "⬅️ Back",
    "admin.btn.cancel": "⬅️ Cancel",
    "admin.btn.confirm": "✅ Confirm",
    "admin.btn.create": "✅ Create",
    "admin.btn.delete": "🗑 Delete",
    "admin.btn.delete_confirm": "🗑 Yes, delete",
    "admin.btn.hide": "🚫 Hide",
    "admin.btn.show": "✅ Show",
    "admin.btn.name": "✏️ Name",
    "admin.btn.description": "📝 Description",
    "admin.label.branches": "📍 Branches",
    # --- Admin panel: main menu -------------------------------------------------
    "admin.menu.services": "💇 Services",
    "admin.menu.barbers": "👨‍💈 Barbers",
    "admin.menu.schedule": "🕐 Schedule",
    "admin.menu.exceptions": "🚫 Exceptions",
    "admin.menu.appointments": "📅 Appointments",
    "admin.menu.clients": "👥 Customers",
    "admin.menu.stats": "📊 Statistics",
    "admin.menu.export": "📥 Export CSV",
    "admin.menu.branches": "📍 Branches",
    "admin.menu.staff": "🧑‍💼 Staff",
    "admin.menu.billing": "💳 Plan",
    "admin.menu.settings": "⚙️ Settings",
    "admin.menu.my_language": "🌐 My language",
    "admin.menu.back_to_menu": "⬅️ To menu",
    "admin.menu.title": "🛠 <b>Admin panel</b>\n\nChoose a section:",
    # --- Admin panel: branches ---------------------------------------------------
    "admin.branches.add": "➕ Add branch",
    "admin.branch.address": "📝 Address",
    "admin.branch.back": "⬅️ To branches",
    # --- Admin panel: staff --------------------------------------------------------
    "admin.staff.add": "➕ Add staff member",
    "admin.staff.role": "🔄 Role",
    "admin.staff.deactivate": "🚫 Deactivate",
    "admin.staff.deactivate_confirm": "🚫 Yes, deactivate",
    "admin.staff.back": "⬅️ To staff",
    "admin.role.tenant_owner": "Owner",
    "admin.role.tenant_admin": "Administrator",
    "admin.role.manager": "Manager",
    "admin.role.receptionist": "Receptionist",
    "admin.role.barber": "Barber",
    # --- Admin panel: services -----------------------------------------------------
    "admin.services.add": "➕ Add service",
    "admin.service.duration": "⏱ Duration",
    "admin.service.price": "💰 Price",
    "admin.service.back": "⬅️ To services",
    # --- Admin panel: barbers --------------------------------------------------------
    "admin.barbers.add": "➕ Add barber",
    "admin.barber.name": "✏️ Name",
    "admin.barber.back": "⬅️ To barbers",
    # --- Admin panel: schedule and exceptions ------------------------------------------
    "admin.schedule.whole_branch": "🏠 Whole branch",
    "admin.schedule.day_off": "day off",
    "admin.schedule.set_hours": "✏️ Set hours",
    "admin.schedule.make_day_off": "🚫 Make it a day off",
    "admin.exceptions.special_hours": "special hours",
    "admin.exceptions.add": "➕ Add exception",
    # --- Admin panel: appointments -----------------------------------------------------
    "admin.appointments.cancel_day": "❌ Cancel a whole day",
    "admin.appointment.reschedule": "🔄 Reschedule",
    "admin.appointment.cancel": "❌ Cancel",
    "admin.appointment.no_show": "🚫 No-show",
    "admin.appointment.back": "⬅️ To appointments",
    "admin.bulk_cancel.day_row": "{date} — {count} appt.",
    "admin.bulk_cancel.confirm": "❌ Yes, cancel {count} appt.",
    # --- Admin panel: CSV export --------------------------------------------------------
    "admin.export.7d": "Last 7 days",
    "admin.export.30d": "Last 30 days",
    "admin.export.90d": "Last 90 days",
    "admin.export.all": "All appointments",
    # --- Admin panel: tenant settings -----------------------------------------------------
    "admin.settings.timezone": "🕐 Timezone",
    "admin.settings.currency": "💰 Currency",
    "admin.settings.language": "🗣 Default language",
    "admin.settings.title": "⚙️ <b>Tenant settings</b>",
    "admin.settings.line_name": "Name: {value}",
    "admin.settings.line_slug": "Slug: <code>{slug}</code> (cannot be changed)",
    "admin.settings.line_timezone": "Timezone: {value}",
    "admin.settings.line_currency": "Currency: {value}",
    "admin.settings.line_language": "Default language: {value}",
    "admin.settings.line_status": "Status: {value} (managed separately)",
    "admin.settings.defaults_notice": (
        "⚠️ The timezone, currency and language here are only the default "
        "for FUTURE branches/staff/customers. Existing staff, customers and "
        "branches keep their own values."
    ),
    "admin.settings.not_found": "Tenant not found.",
    "admin.settings.pick_language_prompt": "🗣 Choose the default language for this tenant:",
    "admin.settings.unknown_language": "Unknown language.",
    "admin.settings.confirm_change": "Change «{field}» to <b>{value}</b>?",
    "admin.settings.field_name": "Name",
    "admin.settings.field_timezone": "Timezone",
    "admin.settings.field_currency": "Currency",
    "admin.settings.field_language": "Default language",
    "admin.settings.prompt_name": "Send the tenant's new name.",
    "admin.settings.prompt_timezone": (
        "Send a timezone in IANA format, e.g. Europe/Chisinau.\n\n"
        "⚠️ This is only the default for NEW branches created from now on — "
        "existing branches keep their own timezone."
    ),
    "admin.settings.prompt_currency": (
        "Send a currency code (3 letters), e.g. MDL, RON, EUR.\n\n"
        "⚠️ This is only the default for NEW branches created from now on — "
        "existing branches keep their own currency."
    ),
    "admin.settings.cancel_hint": "To cancel: /cancel",
    "admin.errors.session_expired": "Session expired. Open /admin again.",
    "admin.errors.saved": "Saved",
    "admin.language.staff_only": "A personal language is only available to tenant staff.",
    "admin.language.pick_prompt": "🌐 Choose the admin panel interface language, just for you:",
    "admin.language.saved_notice": "✅ Language saved for you personally.",
    "admin.language.unknown_language": "Unknown language.",
    # --- Input validation (Phase 9F) -----------------------------------------
    "validation.field_name_default": "Name",
    "validation.name_too_short": "{field} is too short (minimum 2 characters).",
    "validation.name_too_long": "{field} is too long (maximum {max} characters).",
    "validation.description_too_long": "The description is longer than {max} characters.",
    "validation.duration_format": "Duration is a whole number of minutes, e.g.: 45",
    "validation.duration_range": "Duration must be between {min} and {max} minutes.",
    "validation.duration_step": "Duration must be a multiple of 5 minutes.",
    "validation.price_format": "Price is a number, e.g.: 250 or 250.50",
    "validation.price_negative": "Price cannot be negative.",
    "validation.price_too_high": "Price cannot exceed {max}.",
    "validation.phone_invalid": "Invalid phone number.",
    "validation.time_range_format": "Working hours format: 10:00-19:00",
    "validation.time_range_invalid": "Invalid time. Hours 0-23, minutes 0-59.",
    "validation.time_range_order": "The start of the working day must be before the end.",
    "validation.date_format": "Date format: DD.MM.YYYY, e.g. 25.12.2026",
    "validation.date_past": "That date has already passed — pick today or a later date.",
    "validation.date_too_far": "Date is too far ahead: maximum {max} days.",
    "validation.positive_int": "{field} must be a positive whole number.",
    "validation.telegram_id_not_a_number": (
        "Telegram ID is a number (check with @userinfobot), not a name."
    ),
    "validation.telegram_id_invalid": "Invalid Telegram ID.",
    "validation.timezone_invalid": (
        "Invalid timezone. Use an IANA identifier, "
        "e.g. Europe/Chisinau or Europe/Bucharest."
    ),
    "validation.currency_invalid": "Currency is a 3-letter code, e.g. MDL, RON or EUR.",
    "validation.language_invalid": "Language must be one of {languages}.",
    # --- Admin: common (Phase 9F) -----------------------------------------------
    "admin.common.cancel_hint": "To cancel: /cancel",
    "admin.common.status_updated": "Status updated",
    "admin.common.edit_field_prompt": "✏️ {name}\n\n{prompt}\n\n{cancel_hint}",
    # --- Admin: branches (continued, Phase 9F) ---------------------------------
    "admin.branch.status_active": "active",
    "admin.branch.status_hidden": "hidden",
    "admin.branch.card_status": "👁 Status: {status}",
    "admin.branch.not_found": "Branch not found.",
    "admin.branch.add_title": (
        "➕ <b>New branch</b>\n\nStep 1/2. Send the branch name.\nTo cancel: /cancel"
    ),
    "admin.branch.add_step2": "Step 2/2. Branch address (or «-» to skip)",
    "admin.branch.create_failed": "⚠️ Could not create the branch.",
    "admin.branch.created": "✅ Branch created.\n\n",
    "admin.branch.prompt_name": "Send the branch's new name.",
    "admin.branch.prompt_address": "Send the new address (or «-» to clear it).",
    "admin.branches.empty": "📍 No branches yet. Add the first one.",
    "admin.branches.list_title": "📍 <b>Branches</b> (total {total})",
    # --- Admin: generic field editing (Phase 9F) ---------------------------------
    "admin.editing.session_expired": "Editing session expired. Open /admin again.",
    "admin.editing.unknown_field": "Unknown field.",
    "admin.editing.save_failed": "⚠️ Could not save: the value may conflict with another one.",
    "admin.editing.saved": "✅ Saved\n\n",
    "admin.service.not_found": "Service not found.",
    "admin.barber.not_found": "Barber not found.",
    # --- Admin: services (Phase 9F) -------------------------------------------------
    "admin.service.status_active": "active",
    "admin.service.status_hidden": "hidden",
    "admin.service.card": (
        "💇 <b>{name}</b>\n\n"
        "💰 Price: {price}\n"
        "⏱ Duration: {duration}\n"
        "📝 Description: {description}\n"
        "👁 Status: {status}"
    ),
    "admin.service.branches_prompt": (
        "📍 <b>{name}</b>\n\nAvailability by branch (tap to toggle):"
    ),
    "admin.service.availability_failed": "Could not change availability.",
    "admin.service.add_title": (
        "➕ <b>New service</b>\n\nStep 1/4. Send the service name.\nTo cancel: /cancel"
    ),
    "admin.service.add_step2": "Step 2/4. Duration in minutes (multiple of 5), e.g.: 45",
    "admin.service.add_step3": "Step 3/4. Price, e.g.: 250",
    "admin.service.add_step4": "Step 4/4. Description (or «-» to skip)",
    "admin.service.create_failed": "⚠️ Could not create the service. That name may already exist.",
    "admin.service.created": "✅ Service created\n\n",
    "admin.service.prompt_name": "Send the service's new name.",
    "admin.service.prompt_duration": "Send the new duration in minutes (multiple of 5).",
    "admin.service.prompt_price": "Send the new price, e.g.: 300",
    "admin.service.prompt_description": "Send the new description (or «-» to clear it).",
    "admin.service.delete_confirm": (
        "🗑 Delete service «{name}»?\n\n"
        "If the service has active appointments, deletion will be blocked — "
        "use “Hide” instead."
    ),
    "admin.service.delete_blocked": (
        "The service has active appointments — it can only be hidden."
    ),
    "admin.service.delete_failed": (
        "Could not delete: the service is used in appointment history."
    ),
    "admin.service.deleted": "🗑 Service deleted\n\n",
    "admin.services.empty": "💇 No services yet. Add the first one.",
    "admin.services.list_title": "💇 <b>Services</b> (total {total})",
    "admin.common.deleted_toast": "Deleted",
    # --- Admin: barbers (Phase 9F) -------------------------------------------------
    "admin.barber.schedule_not_set": "not set",
    "admin.barber.card": (
        "👨‍💈 <b>{name}</b>\n\n📝 {description}\n👁 Status: {status}\n🕐 Schedule: {days}"
    ),
    "admin.barber.branches_prompt": (
        "📍 <b>{name}</b>\n\nBranches (tap to assign/unassign):"
    ),
    "admin.barber.cannot_unassign_last_branch": (
        "You can't remove the last branch — the barber would become impossible "
        "to book or schedule. Assign another branch first."
    ),
    "admin.barber.assign_failed": "Could not assign the branch.",
    "admin.barber.add_title": (
        "➕ <b>New barber</b>\n\nStep 1/2. Send the barber's name.\nTo cancel: /cancel"
    ),
    "admin.barber.add_step2": "Step 2/2. Short description (or «-» to skip)",
    "admin.barber.create_failed": "⚠️ Could not create the barber.",
    "admin.barber.created": "✅ Barber created. Don't forget to set their schedule.\n\n",
    "admin.barber.prompt_name": "Send the barber's new name.",
    "admin.barber.prompt_description": "Send the new description (or «-» to clear it).",
    "admin.barber.delete_confirm": (
        "🗑 Delete barber «{name}»?\n\n"
        "If they have active appointments, deletion will be blocked — use “Hide” instead."
    ),
    "admin.barber.delete_blocked": "The barber has active appointments — they can only be hidden.",
    "admin.barber.delete_failed": (
        "Could not delete: the barber is used in appointment history."
    ),
    "admin.barber.deleted": "🗑 Barber deleted\n\n",
    "admin.barbers.empty": "👨‍💈 No barbers yet. Add the first one.",
    "admin.barbers.list_title": "👨‍💈 <b>Barbers</b> (total {total})",
    "admin.barber.field_name": "Name",
    # --- Admin: staff (Phase 9F) -------------------------------------------
    "admin.staff.empty": "🧑‍💼 No staff yet.",
    "admin.staff.list_title": "🧑‍💼 <b>Staff</b> (total {total})",
    "admin.staff.not_found": "Staff member not found.",
    "admin.staff.card_title": "🧑‍💼 <b>{telegram_id}</b>",
    "admin.staff.card_role": "Role: {role}",
    "admin.staff.card_status": "Status: {status}",
    "admin.staff.branches_hint": "Branches (tap to assign/unassign):",
    "admin.staff.all_branches_hint": "This role has access to all of the tenant's branches.",
    "admin.staff.cannot_unassign_last_branch": (
        "You can't remove the last branch — the staff member would lose all "
        "access. Assign another branch first."
    ),
    "admin.staff.assign_failed": "Could not assign the branch.",
    "admin.staff.add_title": (
        "➕ <b>New staff member</b>\n\n"
        "Send the staff member's Telegram ID (check with @userinfobot).\n\n"
        "To cancel: /cancel"
    ),
    "admin.staff.pick_role_prompt": "Choose a role:",
    "admin.staff.create_confirm": (
        "Create staff member <code>{telegram_id}</code> with role <b>{role}</b>?"
    ),
    "admin.staff.telegram_id_taken": "This Telegram ID is already linked to a staff member.",
    "admin.staff.limit_reached": "The plan's staff limit has been reached.",
    "admin.staff.create_failed": "Could not create the staff member.",
    "admin.staff.added_toast": "Staff member added",
    "admin.staff.role_pick_title": "🔄 <b>{telegram_id}</b>\n\nChoose the new role:",
    "admin.staff.role_change_confirm": (
        "Change <code>{telegram_id}</code>'s role to <b>{role}</b>?"
    ),
    "admin.staff.role_or_target_invalid": "Staff member not found or invalid role.",
    "admin.staff.sole_owner_protected": (
        "Not allowed — this is the tenant's only active owner."
    ),
    "admin.staff.role_changed_toast": "Role changed",
    "admin.staff.deactivate_confirm_prompt": "🚫 Deactivate <code>{telegram_id}</code>?",
    "admin.staff.already_deactivated": "This staff member is already deactivated.",
    "admin.staff.actor_unknown": "Could not determine who initiated this.",
    "admin.staff.deactivated_toast": "Deactivated",
    # --- Admin: schedule and exceptions (continued, Phase 9F) ---------------------
    "admin.schedule.add_barber_first": "Add a barber first.",
    "admin.schedule.title_pick_barber": "🕐 <b>Work schedule</b>\n\nChoose a barber:",
    "admin.schedule.pick_branch_title": "🕐 <b>{barber}</b>\n\nChoose a branch:",
    "admin.schedule.no_accessible_branches": "No branches available to you for this barber.",
    "admin.schedule.week_title": "🕐 <b>Schedule: {barber}</b> — 📍{branch}",
    "admin.schedule.pick_day_prompt": "Choose a weekday to change:",
    "admin.schedule.weekday_title": "🕐 <b>{barber} — {weekday}</b>\n\nCurrently: {current}",
    "admin.schedule.invalid_data": "Invalid data.",
    "admin.schedule.set_hours_prompt": (
        "Send the working hours for {weekday} in the format 10:00-19:00\n\nTo cancel: /cancel"
    ),
    "admin.schedule.save_failed": "⚠️ Could not save the schedule.",
    "admin.schedule.hours_saved": "✅ {weekday}: {start}-{end}",
    "admin.schedule.day_off_saved": "✅ {weekday} is now a day off.",
    "admin.schedule.title_exceptions": "🚫 <b>Schedule exceptions</b>",
    "admin.schedule.no_exceptions": "No exceptions scheduled yet.",
    "admin.schedule.exc_scope_whole_branch": "whole branch",
    "admin.schedule.exc_scope_barber_fallback": "barber",
    "admin.schedule.exc_row": "• {date} — {scope}: {detail}",
    "admin.schedule.exc_tap_hint": "Tap an exception to delete it.",
    "admin.schedule.new_exception_title": "🚫 <b>New exception</b>\n\nFor whom?",
    "admin.schedule.invalid_choice": "Invalid choice.",
    "admin.schedule.no_accessible_branches_generic": "No branches available to you.",
    "admin.schedule.pick_branch_generic": "Choose a branch:",
    "admin.schedule.ask_date_prompt": (
        "Send the date in DD.MM.YYYY format, e.g. 31.12.2026\n\nTo cancel: /cancel"
    ),
    "admin.schedule.barber_not_at_branch": "This barber doesn't work at that branch.",
    "admin.schedule.date_mode_prompt": "Date: {date}\n\nWhat now?",
    "admin.schedule.mode_off": "🚫 Day off",
    "admin.schedule.mode_hours": "🕐 Special hours",
    "admin.schedule.ask_hours_prompt": (
        "Send the special working hours in the format 12:00-16:00\n\nTo cancel: /cancel"
    ),
    "admin.schedule.exception_save_failed": "Could not save the exception.",
    "admin.schedule.exception_saved": "✅ Exception saved.",
    "admin.schedule.exception_saved_hours": "✅ Exception saved: {start}-{end}",
    "admin.schedule.exception_not_found": "Exception not found.",
    # --- Admin: appointments (continued, Phase 9F) ---------------------------------
    "admin.appointments.empty": "📅 No upcoming appointments.",
    "admin.appointments.list_title": (
        "📅 <b>Upcoming appointments</b> (total {total})\n\nChoose an appointment:"
    ),
    "admin.appointment.not_found": "Appointment not found.",
    "admin.appointment.invalid": "Invalid appointment.",
    "admin.appointment.cancelled_by_admin_title": "❌ <b>Appointment cancelled by staff</b>\n\n",
    "admin.appointment.cancelled_toast": "Cancelled",
    "admin.appointment.no_show_title": "🚫 <b>Marked: customer no-show</b>\n\n",
    "admin.appointment.no_show_toast": "Marked",
    "admin.bulk_cancel.no_appointments_in_branch": "📅 No upcoming appointments at «{branch}».",
    "admin.bulk_cancel.pick_date_prompt": "❌ <b>Cancel a whole day</b>\n\nChoose a date:",
    "admin.bulk_cancel.no_accessible_branches": "📅 No branches available to you.",
    "admin.bulk_cancel.pick_branch_prompt": "❌ <b>Cancel a whole day</b>\n\nChoose a branch:",
    "admin.bulk_cancel.invalid_date": "Invalid date.",
    "admin.bulk_cancel.no_active_appointments": "There are no active appointments on that day.",
    "admin.bulk_cancel.confirm_title": (
        "❌ <b>Confirm cancellation</b>\n\n"
        "Branch: <b>{branch}</b>\n"
        "Date: <b>{date}</b>\n"
        "Appointments: <b>{count}</b>\n\n"
        "Every customer will get a cancellation notice."
    ),
    "admin.bulk_cancel.done_title": (
        "✅ <b>Cancelled {count} appointments on {date}</b> — 📍{branch}\n\n"
        "Sending notifications to customers..."
    ),
    "admin.bulk_cancel.done_toast": "Cancelled: {count}",
    # --- Admin: statistics, customers, export (Phase 9F) -------------------------
    "admin.stats.title": "📊 <b>Statistics</b>",
    "admin.stats.total_appointments": "📅 Total appointments: <b>{value}</b>",
    "admin.stats.upcoming": "⏭ Upcoming: <b>{value}</b>",
    "admin.stats.today": "📆 Today: <b>{value}</b>",
    "admin.stats.this_month": "🗓 This month: <b>{value}</b>",
    "admin.stats.cancelled_month": "🚫 Cancelled this month: <b>{value}</b>",
    "admin.stats.clients": "👥 Customers: <b>{value}</b>",
    "admin.stats.revenue_today": "💰 Revenue today: <b>{value}</b>",
    "admin.stats.revenue_month": "💰 Revenue this month: <b>{value}</b>",
    "admin.stats.top_services_header": "🔥 <b>Popular services (this month)</b>",
    "admin.stats.top_barbers_header": "👨‍💈 <b>Barbers (this month)</b>",
    "admin.clients.empty": "👥 No customers yet.",
    "admin.clients.list_title": "👥 <b>Customers</b> (total {total})",
    "admin.clients.row": "• {name} — {count} appt.{blocked}\n  {telegram_id}",
    "admin.export.title": "📥 <b>Export appointments to CSV</b>\n\nChoose a period:",
    "admin.export.no_rights": "Not enough rights to export.",
    "admin.export.period_all": "all appointments",
    "admin.export.period_days": "last {days} days",
    "admin.export.invalid_period": "Invalid period.",
    "admin.export.caption": "📥 Appointment export ({label})",
    "admin.export.sent_toast": "File sent",
    "admin.errors.no_rights_or_branch_unavailable": (
        "Not enough rights, or the branch is unavailable."
    ),
}
