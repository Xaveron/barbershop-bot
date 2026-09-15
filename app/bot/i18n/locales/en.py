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
}
