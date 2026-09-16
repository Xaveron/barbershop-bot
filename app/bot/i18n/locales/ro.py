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
    "booking.step_branch": "Alege locația:",
    "booking.branch_gone": "Această locație nu mai este disponibilă.",
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
    "error.barber_not_at_branch": "Frizerul nu lucrează la această locație. Alege altul.",
    "error.branch_unavailable": "Această locație nu mai este disponibilă. Alege alta.",
    "error.service_not_at_branch": "Acest serviciu nu este disponibil la locația selectată.",
    "error.barber_not_provide_service": "Frizerul nu oferă acest serviciu. Alege altul.",
    "error.slot_busy": "Ora este deja ocupată. Te rugăm să alegi alta.",
    "error.slot_race": "Cineva a ocupat ora cu o secundă mai devreme. Alege alt interval.",
    "error.create_failed": "Nu am reușit să creez programarea. Încearcă din nou.",
    "error.move_failed": "Nu am reușit să mut programarea. Încearcă din nou.",
    "error.appointment_not_found": "Programarea nu a fost găsită.",
    "error.barber_locked": (
        "Cineva face chiar acum o programare la acest maestru. Încearcă peste un minut."
    ),
    # --- Configurarea arendatorului ---------------------------------------------
    "onboarding.not_active_customer": (
        "🚧 Acest salon de frizerie este încă în curs de configurare și nu "
        "acceptă programări deocamdată. Revino în curând!"
    ),
    "onboarding.owner_claimed": "👋 Ai fost desemnat proprietarul acestui salon.",
    "onboarding.welcome": (
        "🏪 <b>Configurare salon</b>\n\n"
        "Hai să configurăm salonul tău în câțiva pași: locație, servicii, frizeri "
        "și program de lucru. Progresul se salvează — poți continua oricând."
    ),
    "onboarding.step_business_name": "Pasul 1. Cum se numește salonul tău?",
    "onboarding.step_branch_name": "Pasul 2. Numele primei locații (de ex. „Centru”).",
    "onboarding.step_branch_timezone": (
        "Fusul orar al locației — un identificator IANA, de ex. Europe/Chisinau "
        "sau Europe/Bucharest.\n\nValoare implicită: {default}. Trimite propria "
        "valoare sau „-” pentru a o păstra."
    ),
    "onboarding.step_branch_currency": (
        "Moneda locației — un cod din trei litere, de ex. MDL, RON sau EUR.\n\n"
        "Implicit: {default}. Trimite propriul cod sau „-” pentru a-l păstra."
    ),
    "onboarding.step_service_name": "Pasul 3. Numele primului serviciu (de ex. „Tuns”).",
    "onboarding.step_service_duration": "Durata serviciului în minute, de ex.: 45",
    "onboarding.step_service_price": "Prețul serviciului, de ex.: 250",
    "onboarding.step_barber_name": "Pasul 4. Numele primului frizer.",
    "onboarding.step_schedule_hours": (
        "Pasul 5. Programul de lucru al frizerului pentru fiecare zi a "
        "săptămânii, în formatul 10:00-19:00."
    ),
    "onboarding.invalid_timezone": (
        "Fus orar invalid. Folosește un identificator IANA, de ex. Europe/Chisinau."
    ),
    "onboarding.invalid_currency": "Monedă invalidă. Un cod din trei litere, de ex. MDL.",
    "onboarding.invalid_name": "Numele este prea scurt sau prea lung (2-120 caractere).",
    "onboarding.invalid_duration": "Durata e un număr întreg de minute, 5-480, multiplu de 5.",
    "onboarding.invalid_price": "Prețul se indică printr-un număr, de ex.: 250 sau 250.50",
    "onboarding.invalid_hours": "Formatul orelor de lucru: 10:00-19:00",
    "onboarding.review_title": "📋 <b>Verificare înainte de lansare</b>",
    "onboarding.review_ready": "✅ Totul este gata! Poți lansa salonul.",
    "onboarding.review_not_ready": "Încă nu ești gata de lansare:",
    "onboarding.missing_branch": "— nicio locație activă",
    "onboarding.missing_service": "— niciun serviciu activ",
    "onboarding.missing_barber": "— niciun frizer asociat unei locații",
    "onboarding.missing_schedule": "— acest frizer nu are program de lucru setat",
    "onboarding.btn_activate": "🚀 Lansează salonul",
    "onboarding.btn_continue": "➡️ Continuă configurarea",
    "onboarding.activated": (
        "🎉 Salonul tău este live! Clienții pot face programări, iar panoul "
        "complet de administrare este disponibil (/admin)."
    ),
    "onboarding.activation_blocked": (
        "Încă nu poți lansa — finalizează mai întâi configurarea (vezi lista de mai sus)."
    ),
    # --- Facturare (Phase 6) --------------------------------------------------
    "billing.limit_reached": (
        "Limita planului a fost atinsă pentru «{limit_name}»: {current}/{maximum}."
    ),
    "billing.feature_not_available": (
        "Funcția «{feature_name}» nu este disponibilă în planul tău."
    ),
    "billing.subscription_inactive": (
        "Abonamentul este inactiv. Contactează proprietarul salonului."
    ),
    "billing.try_again": "Nu s-a putut procesa cererea, încearcă din nou.",
    "billing.limit.max_branches": "Sucursale",
    "billing.limit.max_barbers": "Frizeri",
    "billing.limit.max_staff": "Personal",
    "billing.limit.max_services": "Servicii",
    "billing.limit.max_monthly_appointments": "Programări pe lună",
    "billing.feature.basic_booking": "Programare de bază",
    "billing.feature.reminders": "Mementouri",
    "billing.feature.csv_export": "Export CSV",
    "billing.feature.analytics": "Analitică",
    "billing.status.trialing": "Perioadă de probă",
    "billing.status.active": "Activ",
    "billing.status.past_due": "Restanță",
    "billing.status.canceled": "Anulat",
    "billing.status.expired": "Expirat",
    "billing.screen_title": "💳 Plan",
    "billing.current_plan": "Plan: <b>{plan_name}</b>",
    "billing.subscription_status": "Stare abonament: {status}",
    "billing.features_header": "Funcții:",
    "billing.limits_header": "Limite:",
    "billing.limit_line": "{limit_name}: {current}/{maximum}",
    "billing.limit_line_unlimited": "{limit_name}: {current}/∞",
    "billing.feature_line_on": "✅ {feature_name}",
    "billing.feature_line_off": "🚫 {feature_name}",
    "billing.dev_change_plan_btn": "🔧 [dev] Schimbă planul: {plan_name}",
    "billing.plan_changed": "Planul a fost schimbat în «{plan_name}».",
    # --- Panou admin: butoane comune (Phase 9F) -------------------------------
    "admin.btn.back": "⬅️ Înapoi",
    "admin.btn.cancel": "⬅️ Anulează",
    "admin.btn.confirm": "✅ Confirmă",
    "admin.btn.create": "✅ Creează",
    "admin.btn.delete": "🗑 Șterge",
    "admin.btn.delete_confirm": "🗑 Da, șterge",
    "admin.btn.hide": "🚫 Ascunde",
    "admin.btn.show": "✅ Afișează",
    "admin.btn.name": "✏️ Denumire",
    "admin.btn.description": "📝 Descriere",
    "admin.label.branches": "📍 Filiale",
    # --- Panou admin: meniul principal -----------------------------------------
    "admin.menu.services": "💇 Servicii",
    "admin.menu.barbers": "👨‍💈 Bărbieri",
    "admin.menu.schedule": "🕐 Program",
    "admin.menu.exceptions": "🚫 Excepții",
    "admin.menu.appointments": "📅 Programări",
    "admin.menu.clients": "👥 Clienți",
    "admin.menu.stats": "📊 Statistici",
    "admin.menu.export": "📥 Export CSV",
    "admin.menu.branches": "📍 Filiale",
    "admin.menu.staff": "🧑‍💼 Angajați",
    "admin.menu.billing": "💳 Abonament",
    "admin.menu.settings": "⚙️ Setări",
    "admin.menu.my_language": "🌐 Limba mea",
    "admin.menu.back_to_menu": "⬅️ La meniu",
    "admin.menu.title": "🛠 <b>Panou admin</b>\n\nAlege o secțiune:",
    # --- Panou admin: filiale ----------------------------------------------------
    "admin.branches.add": "➕ Adaugă filială",
    "admin.branch.address": "📝 Adresă",
    "admin.branch.back": "⬅️ La filiale",
    # --- Panou admin: angajați ----------------------------------------------------
    "admin.staff.add": "➕ Adaugă angajat",
    "admin.staff.role": "🔄 Rol",
    "admin.staff.deactivate": "🚫 Dezactivează",
    "admin.staff.deactivate_confirm": "🚫 Da, dezactivează",
    "admin.staff.back": "⬅️ La angajați",
    "admin.role.tenant_owner": "Proprietar",
    "admin.role.tenant_admin": "Administrator",
    "admin.role.manager": "Manager",
    "admin.role.receptionist": "Recepție",
    "admin.role.barber": "Bărbier",
    # --- Panou admin: servicii ----------------------------------------------------
    "admin.services.add": "➕ Adaugă serviciu",
    "admin.service.duration": "⏱ Durată",
    "admin.service.price": "💰 Preț",
    "admin.service.back": "⬅️ La servicii",
    # --- Panou admin: bărbieri ------------------------------------------------------
    "admin.barbers.add": "➕ Adaugă bărbier",
    "admin.barber.name": "✏️ Nume",
    "admin.barber.back": "⬅️ La bărbieri",
    # --- Panou admin: program și excepții --------------------------------------------
    "admin.schedule.whole_branch": "🏠 Toată filiala",
    "admin.schedule.day_off": "zi liberă",
    "admin.schedule.set_hours": "✏️ Setează orele",
    "admin.schedule.make_day_off": "🚫 Fă zi liberă",
    "admin.exceptions.special_hours": "ore speciale",
    "admin.exceptions.add": "➕ Adaugă excepție",
    # --- Panou admin: programări -------------------------------------------------------
    "admin.appointments.cancel_day": "❌ Anulează pe o zi",
    "admin.appointment.reschedule": "🔄 Reprogramează",
    "admin.appointment.cancel": "❌ Anulează",
    "admin.appointment.no_show": "🚫 Nu s-a prezentat",
    "admin.appointment.back": "⬅️ La programări",
    "admin.bulk_cancel.day_row": "{date} — {count} progr.",
    "admin.bulk_cancel.confirm": "❌ Da, anulează {count} progr.",
    # --- Panou admin: export CSV --------------------------------------------------------
    "admin.export.7d": "Ultimele 7 zile",
    "admin.export.30d": "Ultimele 30 zile",
    "admin.export.90d": "Ultimele 90 zile",
    "admin.export.all": "Toate programările",
    # --- Panou admin: setările arendașului -----------------------------------------------
    "admin.settings.timezone": "🕐 Fus orar",
    "admin.settings.currency": "💰 Monedă",
    "admin.settings.language": "🗣 Limba implicită",
    "admin.settings.title": "⚙️ <b>Setările arendașului</b>",
    "admin.settings.line_name": "Denumire: {value}",
    "admin.settings.line_slug": "Slug: <code>{slug}</code> (nu se poate schimba)",
    "admin.settings.line_timezone": "Fus orar: {value}",
    "admin.settings.line_currency": "Monedă: {value}",
    "admin.settings.line_language": "Limba implicită: {value}",
    "admin.settings.line_status": "Stare: {value} (gestionată separat)",
    "admin.settings.defaults_notice": (
        "⚠️ Fusul orar, moneda și limba de aici sunt doar valori implicite "
        "pentru filiale/angajați/clienți VIITORI. Angajații, clienții și "
        "filialele existente își păstrează propriile valori."
    ),
    "admin.settings.not_found": "Arendașul nu a fost găsit.",
    "admin.settings.pick_language_prompt": "🗣 Alege limba implicită pentru acest arendaș:",
    "admin.settings.unknown_language": "Limbă necunoscută.",
    "admin.settings.confirm_change": "Schimbi «{field}» în <b>{value}</b>?",
    "admin.settings.field_name": "Denumire",
    "admin.settings.field_timezone": "Fus orar",
    "admin.settings.field_currency": "Monedă",
    "admin.settings.field_language": "Limba implicită",
    "admin.settings.prompt_name": "Trimite noua denumire a arendașului.",
    "admin.settings.prompt_timezone": (
        "Trimite fusul orar în format IANA, de exemplu Europe/Chisinau.\n\n"
        "⚠️ Este doar valoarea implicită pentru filialele NOI create de acum "
        "înainte — fusul orar al filialelor existente nu se schimbă."
    ),
    "admin.settings.prompt_currency": (
        "Trimite codul monedei (3 litere), de exemplu MDL, RON, EUR.\n\n"
        "⚠️ Este doar valoarea implicită pentru filialele NOI create de acum "
        "înainte — moneda filialelor existente nu se schimbă."
    ),
    "admin.settings.cancel_hint": "Pentru anulare: /cancel",
    "admin.errors.session_expired": "Sesiunea a expirat. Deschide din nou /admin.",
    "admin.errors.saved": "Salvat",
    "admin.language.staff_only": "Limba personală este disponibilă doar angajaților arendașului.",
    "admin.language.pick_prompt": "🌐 Alege limba interfeței panoului admin, personal pentru tine:",
    "admin.language.saved_notice": "✅ Limba a fost salvată personal pentru tine.",
    "admin.language.unknown_language": "Limbă necunoscută.",
    # --- Validarea datelor introduse (Phase 9F) -------------------------------
    "validation.field_name_default": "Denumirea",
    "validation.name_too_short": "{field} este prea scurt(ă) (minimum 2 caractere).",
    "validation.name_too_long": "{field} este prea lung(ă) (maximum {max} caractere).",
    "validation.description_too_long": "Descrierea are peste {max} caractere.",
    "validation.duration_format": "Durata se indică în minute întregi, de exemplu: 45",
    "validation.duration_range": "Durata trebuie să fie între {min} și {max} minute.",
    "validation.duration_step": "Durata trebuie să fie un multiplu de 5 minute.",
    "validation.price_format": "Prețul se indică numeric, de exemplu: 250 sau 250.50",
    "validation.price_negative": "Prețul nu poate fi negativ.",
    "validation.price_too_high": "Prețul nu poate depăși {max}.",
    "validation.phone_invalid": "Număr de telefon incorect.",
    "validation.time_range_format": "Formatul orelor de lucru: 10:00-19:00",
    "validation.time_range_invalid": "Oră incorectă. Ore 0-23, minute 0-59.",
    "validation.time_range_order": "Începutul programului trebuie să fie înainte de sfârșit.",
    "validation.date_format": "Formatul datei: ZZ.LL.AAAA, de exemplu 25.12.2026",
    "validation.date_past": "Data a trecut deja — alege ziua de azi sau o dată ulterioară.",
    "validation.date_too_far": "Data e prea departe: maximum {max} zile înainte.",
    "validation.positive_int": "{field} trebuie să fie un număr întreg pozitiv.",
    "validation.telegram_id_not_a_number": (
        "Telegram ID este un număr (verifică la @userinfobot), nu un nume."
    ),
    "validation.telegram_id_invalid": "Telegram ID incorect.",
    "validation.timezone_invalid": (
        "Fus orar incorect. Indică un identificator IANA, "
        "de exemplu Europe/Chisinau sau Europe/Bucharest."
    ),
    "validation.currency_invalid": "Moneda este un cod din 3 litere, de exemplu MDL, RON sau EUR.",
    "validation.language_invalid": "Limba trebuie să fie una dintre {languages}.",
    # --- Admin: general (Phase 9F) -----------------------------------------------
    "admin.common.cancel_hint": "Pentru anulare: /cancel",
    "admin.common.status_updated": "Stare actualizată",
    "admin.common.edit_field_prompt": "✏️ {name}\n\n{prompt}\n\n{cancel_hint}",
    # --- Admin: filiale (continuare, Phase 9F) ---------------------------------
    "admin.branch.status_active": "activă",
    "admin.branch.status_hidden": "ascunsă",
    "admin.branch.card_status": "👁 Stare: {status}",
    "admin.branch.not_found": "Filiala nu a fost găsită.",
    "admin.branch.add_title": (
        "➕ <b>Filială nouă</b>\n\nPasul 1/2. Trimite denumirea filialei.\nPentru anulare: /cancel"
    ),
    "admin.branch.add_step2": "Pasul 2/2. Adresa filialei (sau «-» ca să sari peste)",
    "admin.branch.create_failed": "⚠️ Nu s-a putut crea filiala.",
    "admin.branch.created": "✅ Filiala a fost creată.\n\n",
    "admin.branch.prompt_name": "Trimite noua denumire a filialei.",
    "admin.branch.prompt_address": "Trimite noua adresă (sau «-» ca să o ștergi).",
    "admin.branches.empty": "📍 Încă nu există filiale. Adaugă prima.",
    "admin.branches.list_title": "📍 <b>Filiale</b> (total {total})",
    # --- Admin: editare universală de câmp (Phase 9F) ---------------------------
    "admin.editing.session_expired": "Sesiunea de editare a expirat. Deschide din nou /admin.",
    "admin.editing.unknown_field": "Câmp necunoscut.",
    "admin.editing.save_failed": "⚠️ Nu s-a putut salva: valoarea intră poate în conflict cu alta.",
    "admin.editing.saved": "✅ Salvat\n\n",
    "admin.service.not_found": "Serviciul nu a fost găsit.",
    "admin.barber.not_found": "Bărbierul nu a fost găsit.",
    # --- Admin: servicii (Phase 9F) -------------------------------------------------
    "admin.service.status_active": "activ",
    "admin.service.status_hidden": "ascuns",
    "admin.service.card": (
        "💇 <b>{name}</b>\n\n"
        "💰 Preț: {price}\n"
        "⏱ Durată: {duration}\n"
        "📝 Descriere: {description}\n"
        "👁 Stare: {status}"
    ),
    "admin.service.branches_prompt": (
        "📍 <b>{name}</b>\n\nDisponibilitate pe filiale (apasă pentru a comuta):"
    ),
    "admin.service.availability_failed": "Nu s-a putut schimba disponibilitatea.",
    "admin.service.add_title": (
        "➕ <b>Serviciu nou</b>\n\nPasul 1/4. Trimite denumirea serviciului.\n"
        "Pentru anulare: /cancel"
    ),
    "admin.service.add_step2": "Pasul 2/4. Durata în minute (multiplu de 5), de exemplu: 45",
    "admin.service.add_step3": "Pasul 3/4. Prețul, de exemplu: 250",
    "admin.service.add_step4": "Pasul 4/4. Descriere (sau «-» ca să sari peste)",
    "admin.service.create_failed": (
        "⚠️ Nu s-a putut crea serviciul. Poate că această denumire există deja."
    ),
    "admin.service.created": "✅ Serviciul a fost creat\n\n",
    "admin.service.prompt_name": "Trimite noua denumire a serviciului.",
    "admin.service.prompt_duration": "Trimite noua durată în minute (multiplu de 5).",
    "admin.service.prompt_price": "Trimite noul preț, de exemplu: 300",
    "admin.service.prompt_description": "Trimite noua descriere (sau «-» ca să o ștergi).",
    "admin.service.delete_confirm": (
        "🗑 Ștergi serviciul «{name}»?\n\n"
        "Dacă serviciul are programări active, ștergerea va fi blocată — "
        "folosește «Ascunde»."
    ),
    "admin.service.delete_blocked": (
        "Serviciul are programări active — poate fi doar ascuns."
    ),
    "admin.service.delete_failed": (
        "Nu s-a putut șterge: serviciul este folosit în istoricul programărilor."
    ),
    "admin.service.deleted": "🗑 Serviciul a fost șters\n\n",
    "admin.services.empty": "💇 Încă nu există servicii. Adaugă primul.",
    "admin.services.list_title": "💇 <b>Servicii</b> (total {total})",
    "admin.common.deleted_toast": "Șters",
    # --- Admin: bărbieri (Phase 9F) -------------------------------------------------
    "admin.barber.schedule_not_set": "nesetat",
    "admin.barber.card": (
        "👨‍💈 <b>{name}</b>\n\n📝 {description}\n👁 Stare: {status}\n🕐 Program: {days}"
    ),
    "admin.barber.branches_prompt": (
        "📍 <b>{name}</b>\n\nFiliale (apasă pentru a atribui/dezatribui):"
    ),
    "admin.barber.cannot_unassign_last_branch": (
        "Nu poți elimina ultima filială — bărbierul nu ar mai putea fi "
        "programat sau avea un program. Atribuie mai întâi altă filială."
    ),
    "admin.barber.assign_failed": "Nu s-a putut atribui filiala.",
    "admin.barber.add_title": (
        "➕ <b>Bărbier nou</b>\n\nPasul 1/2. Trimite numele bărbierului.\nPentru anulare: /cancel"
    ),
    "admin.barber.add_step2": "Pasul 2/2. Descriere scurtă (sau «-» ca să sari peste)",
    "admin.barber.create_failed": "⚠️ Nu s-a putut crea bărbierul.",
    "admin.barber.created": "✅ Bărbierul a fost creat. Nu uita să setezi programul.\n\n",
    "admin.barber.prompt_name": "Trimite noul nume al bărbierului.",
    "admin.barber.prompt_description": "Trimite noua descriere (sau «-» ca să o ștergi).",
    "admin.barber.delete_confirm": (
        "🗑 Ștergi bărbierul «{name}»?\n\n"
        "Dacă are programări active, ștergerea va fi blocată — folosește «Ascunde»."
    ),
    "admin.barber.delete_blocked": (
        "Bărbierul are programări active — poate fi doar ascuns."
    ),
    "admin.barber.delete_failed": (
        "Nu s-a putut șterge: bărbierul este folosit în istoricul programărilor."
    ),
    "admin.barber.deleted": "🗑 Bărbierul a fost șters\n\n",
    "admin.barbers.empty": "👨‍💈 Încă nu există bărbieri. Adaugă primul.",
    "admin.barbers.list_title": "👨‍💈 <b>Bărbieri</b> (total {total})",
    "admin.barber.field_name": "Numele",
    # --- Admin: angajați (Phase 9F) -------------------------------------------
    "admin.staff.empty": "🧑‍💼 Încă nu există angajați.",
    "admin.staff.list_title": "🧑‍💼 <b>Angajați</b> (total {total})",
    "admin.staff.not_found": "Angajatul nu a fost găsit.",
    "admin.staff.card_title": "🧑‍💼 <b>{telegram_id}</b>",
    "admin.staff.card_role": "Rol: {role}",
    "admin.staff.card_status": "Stare: {status}",
    "admin.staff.branches_hint": "Filiale (apasă pentru a atribui/dezatribui):",
    "admin.staff.all_branches_hint": "Acest rol are acces la toate filialele arendașului.",
    "admin.staff.cannot_unassign_last_branch": (
        "Nu poți elimina ultima filială — angajatul ar rămâne fără acces. "
        "Atribuie mai întâi altă filială."
    ),
    "admin.staff.assign_failed": "Nu s-a putut atribui filiala.",
    "admin.staff.add_title": (
        "➕ <b>Angajat nou</b>\n\n"
        "Trimite Telegram ID-ul angajatului (verifică la @userinfobot).\n\n"
        "Pentru anulare: /cancel"
    ),
    "admin.staff.pick_role_prompt": "Alege rolul:",
    "admin.staff.create_confirm": (
        "Creezi angajatul <code>{telegram_id}</code> cu rolul <b>{role}</b>?"
    ),
    "admin.staff.telegram_id_taken": "Acest Telegram ID este deja asociat unui angajat.",
    "admin.staff.limit_reached": "Limita de angajați din abonament a fost atinsă.",
    "admin.staff.create_failed": "Nu s-a putut crea angajatul.",
    "admin.staff.added_toast": "Angajat adăugat",
    "admin.staff.role_pick_title": "🔄 <b>{telegram_id}</b>\n\nAlege noul rol:",
    "admin.staff.role_change_confirm": (
        "Schimbi rolul <code>{telegram_id}</code> în <b>{role}</b>?"
    ),
    "admin.staff.role_or_target_invalid": "Angajatul nu a fost găsit sau rolul este incorect.",
    "admin.staff.sole_owner_protected": (
        "Nu se poate — este singurul proprietar activ al arendașului."
    ),
    "admin.staff.role_changed_toast": "Rol schimbat",
    "admin.staff.deactivate_confirm_prompt": "🚫 Dezactivezi <code>{telegram_id}</code>?",
    "admin.staff.already_deactivated": "Angajatul este deja dezactivat.",
    "admin.staff.actor_unknown": "Nu s-a putut determina inițiatorul.",
    "admin.staff.deactivated_toast": "Dezactivat",
    # --- Admin: program și excepții (continuare, Phase 9F) ---------------------
    "admin.schedule.add_barber_first": "Adaugă mai întâi un bărbier.",
    "admin.schedule.title_pick_barber": "🕐 <b>Program de lucru</b>\n\nAlege bărbierul:",
    "admin.schedule.pick_branch_title": "🕐 <b>{barber}</b>\n\nAlege filiala:",
    "admin.schedule.no_accessible_branches": (
        "Nu ai filiale disponibile pentru acest bărbier."
    ),
    "admin.schedule.week_title": "🕐 <b>Program: {barber}</b> — 📍{branch}",
    "admin.schedule.pick_day_prompt": "Alege ziua săptămânii de modificat:",
    "admin.schedule.weekday_title": "🕐 <b>{barber} — {weekday}</b>\n\nAcum: {current}",
    "admin.schedule.invalid_data": "Date incorecte.",
    "admin.schedule.set_hours_prompt": (
        "Trimite orele de lucru pentru {weekday} în format 10:00-19:00\n\nPentru anulare: /cancel"
    ),
    "admin.schedule.save_failed": "⚠️ Nu s-a putut salva programul.",
    "admin.schedule.hours_saved": "✅ {weekday}: {start}-{end}",
    "admin.schedule.day_off_saved": "✅ {weekday} este acum zi liberă.",
    "admin.schedule.title_exceptions": "🚫 <b>Excepții de la program</b>",
    "admin.schedule.no_exceptions": "Încă nu sunt excepții programate.",
    "admin.schedule.exc_scope_whole_branch": "toată filiala",
    "admin.schedule.exc_scope_barber_fallback": "bărbier",
    "admin.schedule.exc_row": "• {date} — {scope}: {detail}",
    "admin.schedule.exc_tap_hint": "Apasă pe o excepție ca să o ștergi.",
    "admin.schedule.new_exception_title": "🚫 <b>Excepție nouă</b>\n\nPentru cine?",
    "admin.schedule.invalid_choice": "Alegere incorectă.",
    "admin.schedule.no_accessible_branches_generic": "Nu ai filiale disponibile.",
    "admin.schedule.pick_branch_generic": "Alege filiala:",
    "admin.schedule.ask_date_prompt": (
        "Trimite data în format ZZ.LL.AAAA, de exemplu 31.12.2026\n\nPentru anulare: /cancel"
    ),
    "admin.schedule.barber_not_at_branch": "Bărbierul nu lucrează la această filială.",
    "admin.schedule.date_mode_prompt": "Data: {date}\n\nCe facem?",
    "admin.schedule.mode_off": "🚫 Zi liberă",
    "admin.schedule.mode_hours": "🕐 Ore speciale",
    "admin.schedule.ask_hours_prompt": (
        "Trimite orele speciale de lucru în format 12:00-16:00\n\nPentru anulare: /cancel"
    ),
    "admin.schedule.exception_save_failed": "Nu s-a putut salva excepția.",
    "admin.schedule.exception_saved": "✅ Excepția a fost salvată.",
    "admin.schedule.exception_saved_hours": "✅ Excepția a fost salvată: {start}-{end}",
    "admin.schedule.exception_not_found": "Excepția nu a fost găsită.",
    # --- Admin: programări (continuare, Phase 9F) ---------------------------------
    "admin.appointments.empty": "📅 Nu sunt programări viitoare.",
    "admin.appointments.list_title": (
        "📅 <b>Programări viitoare</b> (total {total})\n\nAlege o programare:"
    ),
    "admin.appointment.not_found": "Programarea nu a fost găsită.",
    "admin.appointment.invalid": "Programare incorectă.",
    "admin.appointment.cancelled_by_admin_title": (
        "❌ <b>Programare anulată de administrator</b>\n\n"
    ),
    "admin.appointment.cancelled_toast": "Anulată",
    "admin.appointment.no_show_title": "🚫 <b>Marcat: clientul nu s-a prezentat</b>\n\n",
    "admin.appointment.no_show_toast": "Marcat",
    "admin.bulk_cancel.no_appointments_in_branch": (
        "📅 Nu sunt programări viitoare la «{branch}»."
    ),
    "admin.bulk_cancel.pick_date_prompt": "❌ <b>Anulare în masă pe o zi</b>\n\nAlege data:",
    "admin.bulk_cancel.no_accessible_branches": "📅 Nu ai filiale disponibile.",
    "admin.bulk_cancel.pick_branch_prompt": "❌ <b>Anulare în masă pe o zi</b>\n\nAlege filiala:",
    "admin.bulk_cancel.invalid_date": "Dată incorectă.",
    "admin.bulk_cancel.no_active_appointments": "Nu sunt programări active în această zi.",
    "admin.bulk_cancel.confirm_title": (
        "❌ <b>Confirmă anularea</b>\n\n"
        "Filiala: <b>{branch}</b>\n"
        "Data: <b>{date}</b>\n"
        "Programări: <b>{count}</b>\n\n"
        "Fiecare client va primi o notificare de anulare."
    ),
    "admin.bulk_cancel.done_title": (
        "✅ <b>{count} programări anulate pe {date}</b> — 📍{branch}\n\n"
        "Trimitem notificări clienților..."
    ),
    "admin.bulk_cancel.done_toast": "Anulate: {count}",
    # --- Admin: statistici, clienți, export (Phase 9F) -------------------------
    "admin.stats.title": "📊 <b>Statistici</b>",
    "admin.stats.total_appointments": "📅 Total programări: <b>{value}</b>",
    "admin.stats.upcoming": "⏭ Viitoare: <b>{value}</b>",
    "admin.stats.today": "📆 Astăzi: <b>{value}</b>",
    "admin.stats.this_month": "🗓 Luna aceasta: <b>{value}</b>",
    "admin.stats.cancelled_month": "🚫 Anulate luna aceasta: <b>{value}</b>",
    "admin.stats.clients": "👥 Clienți: <b>{value}</b>",
    "admin.stats.revenue_today": "💰 Încasări astăzi: <b>{value}</b>",
    "admin.stats.revenue_month": "💰 Încasări luna aceasta: <b>{value}</b>",
    "admin.stats.top_services_header": "🔥 <b>Servicii populare (luna aceasta)</b>",
    "admin.stats.top_barbers_header": "👨‍💈 <b>Bărbieri (luna aceasta)</b>",
    "admin.clients.empty": "👥 Încă nu sunt clienți.",
    "admin.clients.list_title": "👥 <b>Clienți</b> (total {total})",
    "admin.clients.row": "• {name} — {count} progr.{blocked}\n  {telegram_id}",
    "admin.export.title": "📥 <b>Export programări în CSV</b>\n\nAlege perioada:",
    "admin.export.no_rights": "Drepturi insuficiente pentru export.",
    "admin.export.period_all": "toate programările",
    "admin.export.period_days": "ultimele {days} zile",
    "admin.export.invalid_period": "Perioadă incorectă.",
    "admin.export.caption": "📥 Export programări ({label})",
    "admin.export.sent_toast": "Fișier trimis",
    "admin.errors.no_rights_or_branch_unavailable": (
        "Drepturi insuficiente sau filiala nu este disponibilă."
    ),
}
