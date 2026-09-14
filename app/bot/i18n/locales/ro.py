"""Locale română."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # --- Butoane ------------------------------------------------------------
    "btn.book": "💈 Programează-te",
    "btn.my": "📅 Programările mele",
    "btn.services": "💇 Servicii",
    "btn.barbers": "👨‍💈 Frizeri",
    "btn.contacts": "📍 Contacte",
    "btn.faq": "❓ Întrebări",
    "btn.language": "🌐 Limba",
    "btn.admin": "🛠 Panou admin",
    "btn.back": "⬅️ Înapoi",
    "btn.back_to_menu": "⬅️ La meniu",
    "btn.back_to_my": "⬅️ La programările mele",
    "btn.confirm": "✅ Confirmă",
    "btn.cancel": "❌ Anulează",
    "btn.reschedule": "🔄 Reprogramează",
    "btn.cancel_appointment": "❌ Anulează",
    "btn.cancel_yes": "✅ Da, anulez",
    "btn.share_phone": "📱 Trimite numărul",
    "btn.skip": "Omite",
    "btn.open_map": "Deschide pe hartă",
    # --- General ------------------------------------------------------------
    "common.greeting": (
        "💈 <b>{shop}</b>\n\n"
        "Salut, {name}! Aici te programezi la tuns din câteva atingeri, "
        "îți vezi programările și ne găsești pe hartă.\n\n"
        "Alege o acțiune:"
    ),
    "common.main_menu": "Meniul principal. Alege o acțiune:",
    "common.help": (
        "<b>Cum folosești botul</b>\n\n"
        "💈 <b>Programează-te</b> — serviciu, frizer, dată, oră.\n"
        "📅 <b>Programările mele</b> — reprogramare și anulare.\n"
        "💇 <b>Servicii</b> — prețuri și durată.\n"
        "👨‍💈 <b>Frizeri</b> — maeștrii noștri.\n"
        "📍 <b>Contacte</b> — adresa și programul.\n"
        "❓ <b>Întrebări</b> — cele mai frecvente.\n\n"
        "Comenzi: /start — meniu, /language — limba, /cancel — anulează acțiunea."
    ),
    "common.action_cancelled": "Acțiune anulată.",
    "common.error_alert": "A apărut o eroare. Încearcă din nou.",
    "common.error_message": "A apărut o eroare. Încearcă din nou sau scrie /start.",
    "common.outdated_button": "Butonul a expirat. Deschide meniul cu /start.",
    "common.unknown_message": "Nu am înțeles comanda. Folosește meniul de mai jos 👇",
    "common.admin_only": "Această comandă este doar pentru administrator.",
    "common.no_rights": "Drepturi insuficiente.",
    "common.private_only": "Lucrez doar în mesaje private. Scrie-mi direct: /start",
    "common.too_fast": "Prea des, așteaptă o secundă.",
    "common.too_many_messages": "Prea multe mesaje la rând. Așteaptă puțin.",
    # --- Limba --------------------------------------------------------------
    "language.choose": "🌐 Alege limba:",
    "language.saved": "Gata! Limba interfeței: {language}",
    # --- Programare ---------------------------------------------------------
    "booking.step_service": "Pasul 1 din 4 — alege serviciul:",
    "booking.step_barber": "Pasul 2 din 4 — alege frizerul:",
    "booking.step_day": "Pasul 3 din 4 — alege data:",
    "booking.step_time": "Pasul 4 din 4 — alege ora:",
    "booking.no_services": "Deocamdată nu sunt servicii disponibile. Revino mai târziu.",
    "booking.no_barbers": "Momentan nu sunt frizeri disponibili. Revino mai târziu.",
    "booking.no_days": (
        "Frizerul {barber} nu are date libere în următoarele {days} zile.\n\n"
        "Încearcă alt frizer."
    ),
    "booking.no_slots": "Pentru această dată nu au mai rămas ore libere.",
    "booking.service_gone": "Serviciul nu mai este disponibil.",
    "booking.barber_gone": "Frizerul nu mai primește programări.",
    "booking.bad_date": "Dată incorectă.",
    "booking.bad_time": "Oră incorectă.",
    "booking.slot_taken": "Ora tocmai a fost ocupată. Alege alta.",
    "booking.check_details": "Verifică detaliile programării:",
    "booking.confirmed_title": "✅ <b>Programare confirmată!</b>",
    "booking.reminder_note": "Îți amintim cu 24 de ore și cu 2 ore înainte de vizită.",
    "booking.done": "Gata!",
    "booking.declined": "Programarea a fost anulată. Revenim la meniu.",
    "booking.session_expired": "Sesiunea a expirat, o luăm de la început.",
    "booking.ask_phone": (
        "📱 Lasă un număr de telefon — frizeria te contactează dacă se schimbă ceva.\n\n"
        "Apasă butonul de mai jos sau trimite numărul într-un mesaj."
    ),
    "booking.phone_saved": "Mulțumim! Numărul a fost salvat.",
    "booking.phone_invalid": "Nu pare un număr de telefon. Încearcă din nou sau omite pasul.",
    "booking.phone_skipped": "Bine, continuăm fără număr.",
    # --- Programările mele --------------------------------------------------
    "appointments.empty": (
        "Nu ai programări active.\n\nApasă «💈 Programează-te» ca să alegi o oră."
    ),
    "appointments.title": (
        "📅 <b>Programările tale</b> ({count}):\n\nAlege o programare pentru a o gestiona."
    ),
    "appointments.not_found": "Programarea nu a fost găsită.",
    "appointments.invalid": "Programare incorectă.",
    "appointments.cancel_question": "Anulezi această programare?",
    "appointments.cancelled_title": "❌ <b>Programare anulată</b>",
    "appointments.cancelled_toast": "Programare anulată",
    "appointments.no_days_to_move": (
        "Frizerul nu are date libere pentru reprogramare. "
        "Încearcă mai târziu sau anulează și creează una nouă."
    ),
    "appointments.move_title": "🔄 <b>Reprogramare</b>\n\nOra actuală:",
    "appointments.move_choose_day": "Alege data nouă:",
    "appointments.move_choose_time": "🔄 <b>Reprogramare</b>\n\n📅 {day}\nAlege ora nouă:",
    "appointments.move_summary": "Mutăm programarea la:",
    "appointments.moved_title": "🔄 <b>Programare mutată</b>",
    "appointments.move_session_expired": "Sesiunea de reprogramare a expirat.",
    "appointments.no_slots_for_day": "Pentru această dată nu au mai rămas ore.",
    "appointments.move_cancelled": "Reprogramare anulată",
    "appointments.moved_by_shop": "🔄 <b>Frizeria ți-a mutat programarea</b>",
    "appointments.questions": "Întrebări: {phone}",
    "appointments.cancelled_by_shop": "❌ <b>Frizeria ți-a anulat programarea</b>",
    "appointments.apologies": "Ne cerem scuze. Contactează-ne: {phone}",
    # --- Info ---------------------------------------------------------------
    "info.services_title": "💇 <b>Servicii și prețuri</b>",
    "info.services_empty": "Lista de servicii este goală.",
    "info.barbers_title": "👨‍💈 <b>Frizerii noștri</b>",
    "info.barbers_empty": "Lista frizerilor este goală.",
    "info.schedule_title": "🕐 <b>Program de lucru</b>",
    "info.schedule_unknown": "Programul se precizează",
    "info.day_off": "zi liberă",
    # --- FAQ ----------------------------------------------------------------
    "faq.title": "❓ <b>Întrebări frecvente</b>",
    "faq.q1": "Trebuie să vin mai devreme?",
    "faq.a1": "Ajunge să vii cu 5 minute înainte — așa maestrul începe la timp.",
    "faq.q2": "Ce se întâmplă dacă întârzii?",
    "faq.a2": (
        "O întârziere mai mare de 10 minute poate scurta serviciul sau cere reprogramare: "
        "după tine urmează alt client."
    ),
    "faq.q3": "Cum anulez sau mut programarea?",
    "faq.a3": (
        "Deschide «📅 Programările mele» și alege acțiunea dorită. "
        "Este posibil cu cel puțin {cancel_lead} minute înainte de început."
    ),
    "faq.q4": "Pot să mă programez fără avans?",
    "faq.a4": "Da, programarea este gratuită. Plata se face la fața locului, cash sau card.",
    "faq.q5": "Câte programări pot avea în același timp?",
    "faq.a5": "Până la {max_active} programări active pentru un cont.",
    "faq.q6": "Cu câte zile înainte pot rezerva?",
    "faq.a6": "Cu {horizon} zile înainte.",
    # --- Statusuri ----------------------------------------------------------
    "status.confirmed": "✅ Confirmată",
    "status.cancelled": "❌ Anulată",
    "status.completed": "☑️ Finalizată",
    "status.no_show": "🚫 Clientul nu a venit",
    # --- Notificări ---------------------------------------------------------
    "notify.reminder_24h": "⏰ <b>Reminder: ai programare mâine</b>",
    "notify.reminder_2h": "⏰ <b>Reminder: programarea ta este peste 2 ore</b>",
    "notify.new_appointment": "🆕 <b>Programare nouă</b>",
    "notify.cancelled_by_client": "🚫 <b>Programare anulată de client</b>",
    "notify.cancelled_by_admin": "🚫 <b>Programare anulată de administrator</b>",
    "notify.client_moved": "🔄 <b>Clientul a mutat programarea</b>",
    "notify.return_reminder": (
        "💈 <b>E timpul pentru un tuns?</b>\n\n"
        "Au trecut {weeks} săpt. de la ultima ta vizită la {shop}.\n"
        "Programează-te din nou!\n\n"
        "Apasă /start pentru a alege un moment convenabil."
    ),
    # --- Erori de domeniu ---------------------------------------------------
    "rule.already_cancelled": "Această programare este deja anulată.",
    "rule.already_completed": "Această programare este deja finalizată.",
    "rule.already_started": "Ora programării a trecut deja.",
    "rule.cancel_deadline": (
        "Poți anula cu cel puțin {minutes} minute înainte de început. "
        "Te rugăm să suni la frizerie."
    ),
    "rule.reschedule_deadline": (
        "Poți muta programarea cu cel puțin {minutes} minute înainte de început."
    ),
    "rule.limit_reached": (
        "Ai deja {count} programări active — este maximul. "
        "Anulează una ca să te programezi din nou."
    ),
    "error.service_unavailable": "Serviciul nu mai este disponibil. Alege altul.",
    "error.barber_unavailable": "Frizerul nu mai primește programări. Alege altul.",
    "error.slot_busy": "Ora este deja ocupată. Te rugăm să alegi alta.",
    "error.slot_race": "Cineva a ocupat ora cu o secundă mai devreme. Alege alt interval.",
    "error.create_failed": "Nu am reușit să creez programarea. Încearcă din nou.",
    "error.move_failed": "Nu am reușit să mut programarea. Încearcă din nou.",
    "error.appointment_not_found": "Programarea nu a fost găsită.",
    "error.barber_locked": (
        "Cineva face chiar acum o programare la acest maestru. Încearcă peste un minut."
    ),
}
