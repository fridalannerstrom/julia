import os
import io
import re
import json
import textwrap
import openpyxl
import markdown2
from markdown2 import markdown
import math
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.safestring import mark_safe
from dotenv import load_dotenv
from openai import OpenAI
from django.conf import settings
from .models import Prompt
from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST


# ──────────────────────────────────────────────────────────────────────────────
# Miljö
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
if os.path.exists("env.py"):
    import env  # noqa: F401

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20,      # global timeout per request
    max_retries=2,   # här är den OK
)

# ── NYTT: gemensamma rubriknycklar i rätt ordning ────────────────────────────
SECTION_KEYS = [
    ("tq_fardighet_text", "TQ Färdighet"),
    ("tq_motivation_text", "TQ Motivation"),
    ("leda_text", "Leda, utveckla och engagera"),
    ("mod_text", "Mod och handlingskraft"),
    ("sjalkannedom_text", "Självkännedom och emotionell stabilitet"),
    ("strategi_text", "Strategiskt tänkande och anpassningsförmåga"),
    ("kommunikation_text", "Kommunikation och samarbete"),
]

# ── Koppling från STIVE-kompetenser -> (sektion_key, svensk_rad) ────────────
HEADER_TO_TARGET = {
    # Leda, utveckla och engagera
    "Leading others":        ("leda_utveckla_och_engagera", "Leda andra"),
    "Engaging others":       ("leda_utveckla_och_engagera", "Engagera andra"),
    "Delegating":            ("leda_utveckla_och_engagera", "Delegera"),
    "Developing others":     ("leda_utveckla_och_engagera", "Utveckla andra"),

    # Mod och handlingskraft
    "Decisiveness":          ("mod_och_handlingskraft", "Beslutsamhet"),
    "Integrity":             ("mod_och_handlingskraft", "Integritet"),
    "Managing conflict":     ("mod_och_handlingskraft", "Hantera konflikter"),

    # Självkännedom och emotionell stabilitet
    "Self-awareness":        ("sjalkannedom_och_emotionell_stabilitet", "Självmedvetenhet"),
    "Resilience":            ("sjalkannedom_och_emotionell_stabilitet", "Uthållighet"),

    # Strategiskt tänkande och anpassningsförmåga
    "Strategic thinking":    ("strategiskt_tankande_och_anpassningsformaga", "Strategiskt fokus"),
    "Adaptability":          ("strategiskt_tankande_och_anpassningsformaga", "Anpassningsförmåga"),

    # Kommunikation och samarbete
    "Teamwork":              ("kommunikation_och_samarbete", "Teamarbete"),
    "Influencing":           ("kommunikation_och_samarbete", "Inflytelserik"),
}


# ── NYTT: liten wrapper för OpenAI-anrop per rubrik ───────────────────────────
def _run_openai(prompt_text: str, style: str, **vars_) -> str:
    try:
        pt = prompt_text.replace("{excel_text}", vars_.get("excel_text", ""))
        pt = pt.replace("{intervju_text}", vars_.get("intervju_text", ""))
        # stöd för fler placeholders utan att krascha
        for k, v in vars_.items():
            placeholder = "{" + k + "}"
            pt = pt.replace(placeholder, v or "")
        filled = (style or "") + "\n\n" + pt

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": filled}],
            temperature=0.2,
            max_tokens=900,
            timeout=20,
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("Tomt svar från OpenAI")
        return content.strip()

    except Exception as e:
        print("⚠️ OpenAI error in _run_openai:", repr(e))
        return (
            "Tyvärr tog AI-svaret för lång tid eller gick inte att hämta just nu. "
            "Försök igen om en liten stund."
        )
    

def _round_to_1_5(x) -> int:
    """
    Runda till heltal mellan 1-5.
    Ex:
      2.2 -> 2
      2.7 -> 3
    (klassisk .5 uppåt, inte bankers rounding)
    """
    try:
        v = float(str(x).replace(",", "."))
    except Exception:
        return 3

    if v < 1:
        v = 1
    if v > 5:
        v = 5

    return int(math.floor(v + 0.5))

def _ai_text_and_ratings_for_section(config, base_prompt_text, style, excel_text, intervju_text=""):
    """
    Kör en prompt som:
      - först skriver en kort textbedömning
      - sedan ger RATINGS_JSON med 1–5 för rätt subskalor för denna sektion.
    Returnerar (full_text, ratings_dict, debug_str).
    """
    section_key = config["section_key"]
    subscales = config["subscales"]

    # Bygg tydlig instruktion som läggs till befintlig prompttext
    rating_instr_lines = [
        "",
        "Viktigt:",
        "1. Baserat på testdatan (och intervju om finns), bedöm varje delkompetens på en skala 1–5:",
        "   1 = Utrymme för utveckling",
        "   2 = Tillräcklig",
        "   3 = God",
        "   4 = Mycket god",
        "   5 = Utmärkt",
        "2. Säkerställ att texten du skriver stämmer överens med de poäng du sätter.",
        "3. Avsluta ALLTID ditt svar med exakt följande format:",
        "   ### RATINGS_JSON",
        "   {",
        f'     "{section_key}": {{'
    ]
    rating_instr_lines += [
        f'       "{sub}": <heltal 1-5>,'
        for sub in subscales[:-1]
    ]
    rating_instr_lines.append(
        f'       "{subscales[-1]}": <heltal 1-5>'
    )
    rating_instr_lines.append("     }")
    rating_instr_lines.append("   }")
    rating_instr_lines.append("")
    rating_instr = "\n".join(rating_instr_lines)

    full_prompt = base_prompt_text.strip() + "\n\n" + rating_instr

    # Kör mot OpenAI
    full_text = _run_openai(
        full_prompt,
        style,
        excel_text=_trim(excel_text),
        intervju_text=_trim(intervju_text or ""),
    )

    # Försök plocka JSON
    parsed = _safe_json_from_text(full_text) or {}
    sec_ratings = parsed.get(section_key, {})

    # Fyll in defaults om något saknas
    cleaned = {}
    debug_lines = []
    for sub in subscales:
        raw = sec_ratings.get(sub)
        try:
            v = int(raw)
        except Exception:
            v = 3
            debug_lines.append(
                f"{section_key}/{sub}: saknade eller ogiltig poäng ('{raw}'), satt till 3"
            )
        v = max(1, min(5, v))
        cleaned[sub] = v
        debug_lines.append(f"{section_key}/{sub}: {v}")

    return full_text, cleaned, "\n".join(debug_lines)

from django.contrib.auth import get_user_model
from django.conf import settings

def get_prompt_owner(fallback_user=None):
    """
    Returnerar den användare vars prompter är 'globala' för hela systemet.
    Typiskt: Veronika. Om inte hittad -> fallback_user.
    """
    User = get_user_model()
    username = getattr(settings, "PROMPT_OWNER_USERNAME", None)

    if username:
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            pass

    # Fallback om något blivit fel
    return fallback_user

# ── NYTT: gör _ratings_table_html konfigurerbar (header av/på) ───────────────
def _ratings_table_html(
    ratings: dict,
    section_filter=None,
    include_css: bool = True
) -> str:
    # Ordning på sektionerna
    default_order = [
        ("leda_utveckla_och_engagera", "Leda, utveckla och engagera"),
        ("mod_och_handlingskraft", "Mod och handlingskraft"),
        ("sjalkannedom_och_emotionell_stabilitet", "Självkännedom och emotionell stabilitet"),
        ("strategiskt_tankande_och_anpassningsformaga", "Strategiskt tänkande och anpassningsförmåga"),
        ("kommunikation_och_samarbete", "Kommunikation och samarbete"),
    ]
    section_order = section_filter or default_order

    def row(label, val: int):
        # 5 cirklar, en fylld
        cells = []
        for i in range(1, 6):
            active_class = " dn-dot--active" if val == i else ""
            cells.append(
                f'<td class="dn-cell"><span class="dn-dot{active_class}"></span></td>'
            )
        return f'<tr><th class="dn-sub">{label}</th>{"".join(cells)}</tr>'

    sections_html = []

    for key, title in section_order:
        if key not in ratings:
            continue

        section_ratings = ratings.get(key, {})
        rows_html = []

        # använd fasta rader från TARGETS om de finns
        target_labels = TARGETS.get(key)
        if target_labels:
            for label in target_labels:
                raw_score = section_ratings.get(label, 3)
                try:
                    v = int(raw_score)
                except Exception:
                    v = 3
                v = max(1, min(5, v))
                rows_html.append(row(label, v))
        else:
            # fallback om ingen TARGETS finns
            for label, raw_score in section_ratings.items():
                try:
                    v = int(raw_score)
                except Exception:
                    v = 3
                v = max(1, min(5, v))
                rows_html.append(row(label, v))

        if rows_html:
            sections_html.append(f"""
            <div class="dn-section">
              <table class="dn-table">
                <tbody>
                  {''.join(rows_html)}
                </tbody>
              </table>
            </div>
            """)

        css = """
        <style>
        .dn-section{
            margin:24px 0;
        }

        .dn-h3{
            font-size:0.95rem;
            margin-bottom:12px;
            font-weight:600;
            color:#111827;
        }

        .dn-table{
            width:100%;
            border-collapse:collapse;
        }

        /* radstil */
        .dn-table tr + tr{
            border-top:1px solid #e5e7eb;
        }

        .dn-sub{
            font-weight:500;
            padding:10px 10px;
            white-space:nowrap;
            color:#111827;
            background:transparent;
        }

        .dn-cell{
            text-align:center;
            padding:10px 4px;
            background:transparent;
        }

        .dn-dot{
            display:inline-flex;
            width:16px;
            height:16px;
            border-radius:999px;
            border:1px solid #d1d5db;
            background:#f9fafb;
            box-shadow:0 0 0 1px rgba(255,255,255,0.9);
        }

        .dn-dot--active{
            background:#7b2cbf;              /* din lila */
            border-color:#7b2cbf;
            box-shadow:0 0 0 3px rgba(123,44,191,0.18);
        }

        @media (max-width:768px){
            .dn-table{
            font-size:0.9rem;
            }
            .dn-dot{
            width:14px;
            height:14px;
            }
        }
        </style>
        """

    return (css if include_css else "") + "\n".join(sections_html)

# --- Målmönster: vad i Excel-raden betyder vilken skala-rad? -----------------
# Flera varianter/engelska namn om dina mallar ändras.
TARGET_PATTERNS = {
    "leda_utveckla_och_engagera": {
        "Leda andra":        [r"leda\s+andra", r"leading\s+others"],
        "Engagera andra":    [r"engagera\s+andra", r"engag(e|era)\w*\s+others"],
        "Delegera":          [r"delegera", r"delegat\w*"],
        "Utveckla andra":    [r"utveckla\s+andra", r"develops?\s+others"],
    },
    "mod_och_handlingskraft": {
        "Beslutsamhet":      [r"beslutsamhet", r"decisiv\w*"],
        "Integritet":        [r"integritet", r"integrit(y|et)"],
        "Hantera konflikter":[r"hantera\s+konflikter", r"conflict\s+(management|handling)"],
    },
    "sjalkannedom_och_emotionell_stabilitet": {
        "Självmedvetenhet":  [r"självmedvet(enhet)?", r"self[-\s]?awareness"],
        "Uthållighet":       [r"uthållighet", r"resilien(ce|s)", r"perseverance"],
    },
    "strategiskt_tankande_och_anpassningsformaga": {
        "Strategiskt fokus": [r"strateg(iskt|ic)\s+(fokus|focus|thinking)"],
        "Anpassningsförmåga":[r"anpassningsf(ö|o)rm(å|a)ga", r"adaptab\w*", r"adapting\s+to\s+change"],
    },
    "kommunikation_och_samarbete": {
        "Teamarbete":        [r"teamarbete", r"team\s*work"],
        "Inflytelserik":     [r"inflytelserik", r"influenc\w*", r"persuasive"],
    },
}

TARGETS = {
    "leda_utveckla_och_engagera": [
        "Leda andra",
        "Engagera andra",
        "Delegera",
        "Utveckla andra",
    ],
    "mod_och_handlingskraft": [
        "Beslutsamhet",
        "Integritet",
        "Hantera konflikter",
    ],
    "sjalkannedom_och_emotionell_stabilitet": [
        "Självmedvetenhet",
        "Uthållighet",
    ],
    "strategiskt_tankande_och_anpassningsformaga": [
        "Strategiskt fokus",
        "Anpassningsförmåga",
    ],
    "kommunikation_och_samarbete": [
        "Teamarbete",
        "Inflytelserik",
    ],
}

SECTION_AI_CONFIG = [
    {
        "prompt_name": "leda",
        "section_key": "leda_utveckla_och_engagera",
        "subscales": [
            "Leda andra",
            "Engagera andra",
            "Delegera",
            "Utveckla andra",
        ],
        "label": "Leda, utveckla och engagera",
        "context_key": "leda_text",
        "table_context_key": "leda_table_html",
    },
    {
        "prompt_name": "mod",
        "section_key": "mod_och_handlingskraft",
        "subscales": [
            "Beslutsamhet",
            "Integritet",
            "Hantera konflikter",
        ],
        "label": "Mod och handlingskraft",
        "context_key": "mod_text",
        "table_context_key": "mod_table_html",
    },
    {
        "prompt_name": "sjalkannedom",
        "section_key": "sjalkannedom_och_emotionell_stabilitet",
        "subscales": [
            "Självmedvetenhet",
            "Uthållighet",
        ],
        "label": "Självkännedom och emotionell stabilitet",
        "context_key": "sjalkannedom_text",
        "table_context_key": "sjalkannedom_table_html",
    },
    {
        "prompt_name": "strategi",
        "section_key": "strategiskt_tankande_och_anpassningsformaga",
        "subscales": [
            "Strategiskt fokus",
            "Anpassningsförmåga",
        ],
        "label": "Strategiskt tänkande och anpassningsförmåga",
        "context_key": "strategi_text",
        "table_context_key": "strategi_table_html",
    },
    {
        "prompt_name": "kommunikation",
        "section_key": "kommunikation_och_samarbete",
        "subscales": [
            "Teamarbete",
            "Inflytelserik",
        ],
        "label": "Kommunikation och samarbete",
        "context_key": "kommunikation_text",
        "table_context_key": "kommunikation_table_html",
    },
]

# För snabb lookup: "leda andra" -> ("leda_utveckla_och_engagera", "Leda andra")
LABEL_TO_TARGET = {}
for section, subs in TARGETS.items():
    for sub in subs:
        LABEL_TO_TARGET[sub.lower()] = (section, sub)


def _map_0_10_to_1_5(x) -> int:
    """Mappa 0–10 (eller 1–10) till 1–5."""
    try:
        v = float(str(x).replace(",", "."))
    except Exception:
        return 3
    # tillåt 0–10 och clamp:a
    if v < 0:
        v = 0
    if v > 10:
        v = 10
    # intervall om 2 poäng: 0-1.99=>1, 2-3.99=>2, 4-5.99=>3, 6-7.99=>4, 8-10=>5
    bucket = 1 + int(v // 2.0)
    if bucket > 5:
        bucket = 5
    if bucket < 1:
        bucket = 1
    return bucket


def _normalize_header_cell(value: str) -> str:
    """
    Tar t.ex. 'Competency Score: Leading others (STIVE)'
    -> 'Leading others'
    """
    if not value:
        return ""
    text = str(value)
    if "Competency Score" in text:
        text = text.split("Competency Score:")[-1]
    if "(" in text:
        text = text.split("(")[0]
    return text.strip()


def _ratings_from_worksheet(ws):
    """
    STIVE-format:
      - Rad 1: rubriker ('Competency Score: Leading others (STIVE)')
      - Rad 2: värden (1–5, ev. decimal)
    Mappar med HEADER_TO_TARGET till svenska etiketter per sektion.
    """
    rows = list(ws.iter_rows(values_only=True))
    debug = []

    if len(rows) < 2:
        debug.append("Excel behöver minst två rader (rubriker + en rad med resultat).")
        return _default_all_three(), debug

    header = rows[0]
    data = rows[1]

    ratings = _default_all_three()

    for col_idx, raw_header in enumerate(header):
        # hoppa över förnamn/efternamn om de ligger först
        if col_idx < 2:
            continue

        comp_name = _normalize_header_cell(raw_header)
        if not comp_name:
            continue

        mapping = HEADER_TO_TARGET.get(comp_name)
        if not mapping:
            debug.append(f"Kolumn {col_idx+1}: '{raw_header}' ignoreras (ingen mapping).")
            continue

        sec_key, sub_label = mapping

        raw_value = data[col_idx] if col_idx < len(data) else None
        if raw_value is None or raw_value == "":
            debug.append(f"{comp_name}: inget värde i rad 2, behåller default.")
            continue

        score = _round_to_1_5(raw_value)
        score = max(1, min(5, score))

        if sec_key not in ratings:
            ratings[sec_key] = {}
        ratings[sec_key][sub_label] = score

        debug.append(f"{comp_name} -> {sub_label}: rå={raw_value} -> {score}")

    return ratings, debug


# ── NYTT: statisk skalförklaring (HTML) med header ───────────────────────────
def _scale_demo_html() -> str:
    demo = {
        "leda_utveckla_och_engagera": {"Exempel": 3},
        "mod_och_handlingskraft": {"Exempel": 3},
        "sjalkannedom_och_emotionell_stabilitet": {"Exempel": 3},
        "strategiskt_tankande_och_anpassningsformaga": {"Exempel": 3},
        "kommunikation_och_samarbete": {"Exempel": 3},
    }
    return _ratings_table_html(demo)


# ──────────────────────────────────────────────────────────────────────────────
# Defaults: skapas per användare om inget finns
# ──────────────────────────────────────────────────────────────────────────────
def ensure_default_prompts_exist(user):
    defaults = {
        "global_style": (
            "❌ Använd aldrig taggar i global_style.\n\n"
            "Global stil ska ENDAST innehålla:\n"
            "- skrivregler\n"
            "- tonalitet\n"
            "- språkbruk (t.ex. “säg grupp, inte team”)\n"
            "- strukturella regler (t.ex. “undvik punktlistor”, “skriv i tredje person”)\n\n"
            "Den får inte innehålla innehållstexter eller taggar som "
            "{excel_text}, {intervju_text}, {uploaded_files}."
        ),
        # NYTT — tolkning av Excelfil
        "tolka_excel_resultat": (
            "Du är en analytiker som ska tolka en Excelfil med testresultat. "
            "Varje kolumn representerar en kompetens och en poäng mellan 1 och 5. "
            "Din uppgift är att identifiera varje kompetens och tilldela ett betyg mellan 1 och 5. "
            "Om du ser decimaltal, avrunda 2,2 till 2 och 2,7 till 3. "
            "Returnera endast JSON i följande format:\n\n"
            "{\n"
            '  "Leda, utveckla och engagera": {\n'
            '    "Leda andra": 3,\n'
            '    "Engagera andra": 4,\n'
            '    "Delegera": 3,\n'
            '    "Utveckla andra": 2\n'
            "  },\n"
            '  "Mod och handlingskraft": {\n'
            '    "Beslutsamhet": 4,\n'
            '    "Integritet": 5,\n'
            '    "Hantera konflikter": 3\n'
            "  }\n"
            "}\n\n"
            "Skriv *endast* JSON, ingen förklarande text."
        ),

        "betygsskala_forklaring": (
            "1 = Tydligt utvecklingsområde. Beteendet stödjer inte kraven i rollen.\n"
            "2 = Acceptabel nivå, men med tydliga utvecklingsbehov i mer komplexa situationer.\n"
            "3 = God nivå. Räcker för de flesta vardagliga krav.\n"
            "4 = Stark nivå. Personen visar ofta beteenden som stödjer rollen väl.\n"
            "5 = Mycket stark nivå. Personen ligger konsekvent högt och fungerar som förebild.\n\n"
            "Specifika beskrivningar per kompetens:\n"
            "- Leda andra: 1 = Den här personen är..., 3 = Den här personen är..., 5 = Den här personen är...\n"
            "- Beslutsamhet: 1 = …, 3 = …, 5 = …\n"
        ),

        # befintliga
        #"testanalys": """Du är en psykolog specialiserad på testtolkning...
#{excel_text}
#""",
        #"intervjuanalys": """Du är en HR-expert...
#{intervjuanteckningar}
#""",
        #"helhetsbedomning": """Du är en HR-expert...
#Test:
#{test_text}

#Intervju:
#{intervju_text}
#""",

        # per-rubrik
        "tq_fardighet": "Skriv TQ Färdighet baserat på testdata.\n\n{ratings_json}\n\n{intervju_text}",
        "tq_motivation": "Identifiera de tre främsta motivationsfaktorerna och beskriv kort.\n\n{ratings_json}\n\n{intervju_text}\n\n{betygsskala_forklaring}",
        "leda": "Skriv bedömning för 'Leda, utveckla och engagera' med fokus på testdata och komplettera med intervju.\n\n{excel_text}\n\n{intervju_text}\n\n{betygsskala_forklaring}",
        "mod": "Skriv bedömning för 'Mod och handlingskraft'.\n\n{ratings_json}\n\n{intervju_text}\n\n{betygsskala_forklaring}",
        "sjalkannedom": "Skriv bedömning för 'Självkännedom och emotionell stabilitet'.\n\n{ratings_json}\n\n{intervju_text}\n\n{betygsskala_forklaring}",
        "strategi": "Skriv bedömning för 'Strategiskt tänkande och anpassningsförmåga'.\n\n{ratings_json}\n\n{intervju_text}\n\n{betygsskala_forklaring}",
        "kommunikation": "Skriv bedömning för 'Kommunikation och samarbete'.\n\n{ratings_json}\n\n{intervju_text}\n\n{betygsskala_forklaring}",

        # sammanställningar
        "styrkor_utveckling_risk": (
            "Sammanfatta till tre listor: Styrkor, Utvecklingsområden, Riskbeteenden. "
            "Använd de sju sektionerna nedan som källa.\n\n"
            "TQ Färdighet:\n{tq_fardighet_text}\n\n"
            "TQ Motivation:\n{tq_motivation_text}\n\n"
            "Leda:\n{leda_text}\n\nMod:\n{mod_text}\n\nSjälvkännedom:\n{sjalkannedom_text}\n\n"
            "Strategi:\n{strategi_text}\n\nKommunikation:\n{kommunikation_text}"
        ),
        "sammanfattande_slutsats": (
            "Skriv en sammanfattande slutsats (1–2 stycken) som väger samman allt. "
            "Ta hänsyn till Styrkor/Utvecklingsområden/Risk och alla sektioner.\n\n"
            "Styrkor/Utvecklingsområden/Risk:\n{sur_text}\n\n"
            "TQ Färdighet:\n{tq_fardighet_text}\n\n"
            "TQ Motivation:\n{tq_motivation_text}\n\n"
            "Leda:\n{leda_text}\n\nMod:\n{mod_text}\n\nSjälvkännedom:\n{sjalkannedom_text}\n\n"
            "Strategi:\n{strategi_text}\n\nKommunikation:\n{kommunikation_text}"
        ),
    }

    for name, text in defaults.items():
        Prompt.objects.get_or_create(user=user, name=name, defaults={"text": text})



# ──────────────────────────────────────────────────────────────────────────────
# Hjälpare
# ──────────────────────────────────────────────────────────────────────────────
def _trim(s: str, max_chars: int = 6500) -> str:
    """Trimma långa texter (behåll början och slut) för att undvika tokenproblem."""
    s = s or ""
    if len(s) <= max_chars:
        return s
    head = s[: max_chars // 2]
    tail = s[- max_chars // 2 :]
    return head + "\n...\n" + tail

def _safe_json_from_text(txt: str):
    """
    Försök plocka JSON efter rubriken RATINGS_JSON.
    Hanterar även ```json ... ``` och whitespace.
    """
    if not txt:
        return None
    m = re.search(r"###\s*RATINGS_JSON\s*(.*)$", txt, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    block = m.group(1).strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", block, flags=re.DOTALL)
    if fence:
        block = fence.group(1)
    else:
        brace = re.search(r"(\{.*\})", block, flags=re.DOTALL)
        if brace:
            block = brace.group(1)

    try:
        return json.loads(block)
    except Exception:
        return None

def _default_all_three():
    """Sista fallback — fyll 3:or överallt så UI alltid renderar."""
    return {
        "leda_utveckla_och_engagera": {
            "Leda andra": 3, "Engagera andra": 3, "Delegera": 3, "Utveckla andra": 3
        },
        "mod_och_handlingskraft": {
            "Beslutsamhet": 3, "Integritet": 3, "Hantera konflikter": 3
        },
        "sjalkannedom_och_emotionell_stabilitet": {
            "Självmedvetenhet": 3, "Uthållighet": 3
        },
        "strategiskt_tankande_och_anpassningsformaga": {
            "Strategiskt fokus": 3, "Anpassningsförmåga": 3
        },
        "kommunikation_och_samarbete": {
            "Teamarbete": 3, "Inflytelserik": 3
        }
    }

def _markdown_to_html(text: str) -> str:
    if not text:
        return ""

    # markdown2 använder andra inställningar än python-markdown
    html = markdown(
        text,
        extras=[
            "fenced-code-blocks",
            "tables",
            "strike",
            "break-on-newline",
            "smarty-pants",
            "spoiler",
            "header-ids",
            "cuddled-lists",
        ]
    )

    return mark_safe(html)

# ──────────────────────────────────────────────────────────────────────────────
# Prompt Editor (om du har en sida för att redigera prompter)
# ──────────────────────────────────────────────────────────────────────────────
@login_required
@csrf_exempt
def prompt_editor(request):
    owner = get_prompt_owner(request.user)
    ensure_default_prompts_exist(owner)

    prompts = Prompt.objects.filter(user=owner)

    # ✅ Bara prompt-ägaren (t.ex. Veronika) får ändra
    can_edit = (request.user == owner)

    if request.method == "POST" and can_edit:
        # reset-logik kan vara kvar om du vill
        if "reset" in request.POST:
            name = request.POST["reset"]
            defaults = {
                "testanalys": """Du är en psykolog specialiserad på testtolkning...""",
                "intervjuanalys": """Du är en HR-expert. Nedan finns intervjuanteckningar...""",
                "helhetsbedomning": """Du är en HR-expert. Nedan finns en testanalys..."""
            }
            if name in defaults:
                prompt = Prompt.objects.get(user=owner, name=name)
                prompt.text = defaults[name]
                prompt.save()
        else:
            for prompt in prompts:
                field_name = f"prompt_{prompt.name}"
                new_text = request.POST.get(field_name)
                if new_text is not None:
                    prompt.text = new_text
                    prompt.save()

    return render(
        request,
        "prompt_editor.html",
        {
            "prompts": prompts,
            "can_edit": can_edit,   # 👈 skickas till templaten
            "owner": owner,
        },
    )

# ──────────────────────────────────────────────────────────────────────────────
# Assistent-sidofält
# ──────────────────────────────────────────────────────────────────────────────


SECTION_TITLES = {
    "leda_utveckla_och_engagera": "Leda, utveckla och engagera",
    "mod_och_handlingskraft": "Mod och handlingskraft",
    "sjalkannedom_och_emotionell_stabilitet": "Självkännedom och emotionell stabilitet",
    "strategiskt_tankande_och_anpassningsformaga": "Strategiskt tänkande och anpassningsförmåga",
    "kommunikation_och_samarbete": "Kommunikation och samarbete",
}

def _build_sidebar_ratings(ratings: dict):
    """
    Gör om ratings-dict till något som är enkelt att loopa i templaten:
    {
      "Leda, utveckla och engagera": [
        {"label": "Leda andra", "value": 5},
        {"label": "Engagera andra", "value": 4},
        ...
      ],
      ...
    }
    """
    grouped = {}

    for sec_key, title in SECTION_TITLES.items():
        sec = ratings.get(sec_key)
        if not sec:
            continue

        grouped[title] = []

        # Försök hålla ordning enligt TARGETS om det finns
        labels_order = TARGETS.get(sec_key) or list(sec.keys())

        for label in labels_order:
            val = sec.get(label)
            if val is None:
                continue
            try:
                v = int(val)
            except Exception:
                v = val
            grouped[title].append({
                "label": label,
                "value": v,
            })

    return grouped

# ──────────────────────────────────────────────────────────────────────────────
# Huvudvy
# ──────────────────────────────────────────────────────────────────────────────


@login_required
@csrf_exempt
def index(request):
    owner = get_prompt_owner(request.user)
    ensure_default_prompts_exist(request.user)

    # ---------- 1) Läs nuvarande steg ----------
    try:
        step = int(request.POST.get("step", "1"))
    except ValueError:
        step = 1

    # ---------- 2) Plocka in state från POST ----------
    context = {
        "step": step,
        "test_text": request.POST.get("test_text", ""),
        "intervju_text": request.POST.get("intervju_text", ""),
        "tq_fardighet_text": request.POST.get("tq_fardighet_text", ""),
        "tq_motivation_text": request.POST.get("tq_motivation_text", ""),
        "leda_text": request.POST.get("leda_text", ""),
        "mod_text": request.POST.get("mod_text", ""),
        "sjalkannedom_text": request.POST.get("sjalkannedom_text", ""),
        "strategi_text": request.POST.get("strategi_text", ""),
        "kommunikation_text": request.POST.get("kommunikation_text", ""),
        "sur_text": request.POST.get("sur_text", ""),
        "slutsats_text": request.POST.get("slutsats_text", ""),
        "cv_text": request.POST.get("cv_text", ""),

        # NYTT – kandidatinfo
        "candidate_name": request.POST.get("candidate_name", ""),
        "candidate_role": request.POST.get("candidate_role", ""),

        # dessa två ersätts av markdown + html
        "uploaded_files_markdown": request.POST.get("uploaded_files_markdown", ""),
        "uploaded_files_html": "",

        "error": "",
    }

    # Om markdown finns i POST → skapa HTML igen
    if context["uploaded_files_markdown"]:
        context["uploaded_files_html"] = markdown(context["uploaded_files_markdown"])

    # Ratings JSON (som string + ev. dict för tabeller)
    ratings_json_str = request.POST.get("ratings_json", "")
    ratings = None
    if ratings_json_str:
        try:
            ratings = json.loads(ratings_json_str)
        except Exception:
            ratings = None

    # ---------- 3) Bygg tabeller (CSS alltid med) ----------
    if ratings:
        context["ratings_json"] = ratings_json_str

        context["leda_table_html"] = mark_safe(_ratings_table_html(
            ratings,
            section_filter=[("leda_utveckla_och_engagera", "Leda, utveckla och engagera")],
            include_css=True,
        ))
        context["mod_table_html"] = mark_safe(_ratings_table_html(
            ratings,
            section_filter=[("mod_och_handlingskraft", "Mod och handlingskraft")],
            include_css=True,
        ))
        context["sjalkannedom_table_html"] = mark_safe(_ratings_table_html(
            ratings,
            section_filter=[("sjalkannedom_och_emotionell_stabilitet", "Självkännedom och emotionell stabilitet")],
            include_css=True,
        ))
        context["strategi_table_html"] = mark_safe(_ratings_table_html(
            ratings,
            section_filter=[("strategiskt_tankande_och_anpassningsformaga", "Strategiskt tänkande och anpassningsförmåga")],
            include_css=True,
        ))
        context["kommunikation_table_html"] = mark_safe(_ratings_table_html(
            ratings,
            section_filter=[("kommunikation_och_samarbete", "Kommunikation och samarbete")],
            include_css=True,
        ))
        context["ratings_sidebar"] = _build_sidebar_ratings(ratings)

    # ---------- 4) POST-actions ----------
    if request.method == "POST":

        # Föregående
        if "prev" in request.POST:
            step = max(1, step - 1)

        # Skapa Word endast på sista steget
        elif "build_doc" in request.POST and step == 10:
            from docx import Document
            from django.http import HttpResponse

            doc = Document()

            def add_section(title, text):
                if text:
                    doc.add_heading(title, level=2)
                    for line in (text or "").split("\n"):
                        line = line.strip()
                        if line:
                            doc.add_paragraph(line)

            add_section("TQ Färdighet", context["tq_fardighet_text"])
            add_section("Styrkor / Utvecklingsområden / Riskbeteenden", context["sur_text"])
            add_section("TQ Motivation – främsta drivkrafter", context["tq_motivation_text"])
            add_section("Leda, utveckla och engagera", context["leda_text"])
            add_section("Mod och handlingskraft", context["mod_text"])
            add_section("Självkännedom och emotionell stabilitet", context["sjalkannedom_text"])
            add_section("Strategiskt tänkande och anpassningsförmåga", context["strategi_text"])
            add_section("Kommunikation och samarbete", context["kommunikation_text"])
            add_section("Sammanfattande slutsats", context["slutsats_text"])

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            response["Content-Disposition"] = 'attachment; filename="bedomning.docx"'
            doc.save(response)
            return response

        # Nästa (inkl AI)
        elif "next" in request.POST:

            try:
                style = Prompt.objects.get(user=request.user, name="global_style").text
            except Prompt.DoesNotExist:
                # fallback om något strular
                style = getattr(settings, "STYLE_INSTRUCTION", "")

            # hämtar förklaringen till betygsskalan (ny prompt)
            try:
                betygsskala_prompt = Prompt.objects.get(
                    user=request.user, name="betygsskala_forklaring"
                ).text
            except Prompt.DoesNotExist:
                betygsskala_prompt = ""

            ratings_json_str = context.get("ratings_json", ratings_json_str or "")

            # ---------- STEG 1 : Excel + Intervju + CV PDF ----------
            if step == 1:
                excel_text = ""
                ws = None

                name = (request.POST.get("candidate_name") or "").strip()
                role = (request.POST.get("candidate_role") or "").strip()

                context["candidate_name"] = name
                context["candidate_role"] = role

                if not name:
                    context["error"] = "Skriv in kandidatens namn."

                # Excel
                if "excel" in request.FILES:
                    try:
                        file = request.FILES["excel"]
                        wb = openpyxl.load_workbook(file)
                        ws = wb.active

                        out = io.StringIO()
                        for row in ws.iter_rows(values_only=True):
                            out.write("\t".join([str(c) if c is not None else "" for c in row]) + "\n")
                        excel_text = out.getvalue()
                    except Exception as e:
                        context["error"] = "Kunde inte läsa excelfilen: " + str(e)[:400]
                else:
                    context["error"] = "Ladda upp en Excelfil."

                # Intervju
                intervju_raw = (request.POST.get("intervju") or "").strip()
                if not intervju_raw and not context["error"]:
                    context["error"] = "Klistra in intervjuanteckningar."

                # CV PDF
                # CV-TEXT (klistra in)
                cv_raw = (request.POST.get("cv_text") or "").strip()

                if not cv_raw:
                    # Lägg bara felmeddelande om vi inte redan har något annat fel
                    if not context["error"]:
                        context["error"] = "Klistra in kandidatens CV som text."
                else:
                    # AI-städa CV-text → markdown
                    clean_prompt = (
                        "Du är en text- och strukturassistent.\n\n"
                        "Rensa och strukturera texten från ett CV, behåll endast relevant innehåll.\n"
                        "Formatera med tydliga rubriker (t.ex. Erfarenhet, Utbildning, Kompetenser) i markdown.\n\n"
                        "Råtext:\n{uploaded_files}"
                    )

                    cleaned = _run_openai(
                        clean_prompt,
                        style,
                        uploaded_files=_trim(cv_raw),
                    )

                    context["uploaded_files_markdown"] = cleaned
                    context["uploaded_files_html"] = markdown(cleaned)

                # Validering
                if context["error"]:
                    step = 1
                else:
                    context["test_text"] = excel_text
                    context["intervju_text"] = intervju_raw

                    # ratings
                    try:
                        ratings, dbg = _ratings_from_worksheet(ws)
                        ratings_json_str = json.dumps(ratings, ensure_ascii=False)
                        context["ratings_json"] = ratings_json_str
                        context["ratings_sidebar"] = _build_sidebar_ratings(ratings)
                    except Exception as e:
                        context["error"] = "Kunde inte tolka betyg från Excel: " + str(e)[:400]
                        step = 1

                    # AI: TQ F/M
                    if not context["error"]:
                        uploaded_trimmed = _trim(context["uploaded_files_markdown"])

                        if not context["tq_fardighet_text"]:
                            P = Prompt.objects.get(user=owner, name="tq_fardighet").text
                            context["tq_fardighet_text"] = _run_openai(
                                P,
                                style,
                                excel_text=_trim(excel_text),
                                intervju_text=_trim(intervju_raw),
                                ratings_json=ratings_json_str,
                                betygsskala_forklaring=betygsskala_prompt,
                                uploaded_files=uploaded_trimmed,
                                candidate_name=context["candidate_name"],
                                candidate_role=context["candidate_role"],
                            )
                        if not context["tq_motivation_text"]:
                            P = Prompt.objects.get(user=owner, name="tq_motivation").text
                            context["tq_motivation_text"] = _run_openai(
                                P,
                                style,
                                excel_text=_trim(excel_text),
                                intervju_text=_trim(intervju_raw),
                                ratings_json=ratings_json_str,    
                                betygsskala_forklaring=betygsskala_prompt,
                                uploaded_files=uploaded_trimmed,
                                candidate_name=context["candidate_name"],
                                candidate_role=context["candidate_role"],
                            )
                        step = 2

            # 2 -> 3: Leda, utveckla och engagera
            elif step == 2:
                if not context["leda_text"]:
                    P = Prompt.objects.get(user=owner, name="leda").text
                    context["leda_text"] = _run_openai(
                        P,
                        style,
                        excel_text=_trim(context["test_text"]),
                        intervju_text=_trim(context["intervju_text"]),
                        ratings_json=ratings_json_str,
                        betygsskala_forklaring=betygsskala_prompt,
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 3

            # 3 -> 4: Mod och handlingskraft
            elif step == 3:
                if not context["mod_text"]:
                    P = Prompt.objects.get(user=owner, name="mod").text
                    context["mod_text"] = _run_openai(
                        P,
                        style,
                        excel_text=_trim(context["test_text"]),
                        intervju_text=_trim(context["intervju_text"]),
                        ratings_json=ratings_json_str,
                        betygsskala_forklaring=betygsskala_prompt,
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 4

            # 4 -> 5: Självkännedom och emotionell stabilitet
            elif step == 4:
                if not context["sjalkannedom_text"]:
                    P = Prompt.objects.get(user=owner, name="sjalkannedom").text
                    context["sjalkannedom_text"] = _run_openai(
                        P,
                        style,
                        excel_text=_trim(context["test_text"]),
                        intervju_text=_trim(context["intervju_text"]),
                        ratings_json=ratings_json_str,
                        betygsskala_forklaring=betygsskala_prompt,
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 5

            # 5 -> 6: Strategiskt tänkande och anpassningsförmåga
            elif step == 5:
                if not context["strategi_text"]:
                    P = Prompt.objects.get(user=owner, name="strategi").text
                    context["strategi_text"] = _run_openai(
                        P,
                        style,
                        excel_text=_trim(context["test_text"]),
                        intervju_text=_trim(context["intervju_text"]),
                        ratings_json=ratings_json_str,
                        betygsskala_forklaring=betygsskala_prompt,
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 6

            # 6 -> 7: Kommunikation och samarbete
            elif step == 6:
                if not context["kommunikation_text"]:
                    P = Prompt.objects.get(user=owner, name="kommunikation").text
                    context["kommunikation_text"] = _run_openai(
                        P,
                        style,
                        excel_text=_trim(context["test_text"]),
                        intervju_text=_trim(context["intervju_text"]),
                        ratings_json=ratings_json_str,
                        betygsskala_forklaring=betygsskala_prompt,
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 7

            # 7 -> 8: SUR (styrkor/utvecklingsområden/risk)
            elif step == 7:
                if not context["sur_text"]:
                    P = Prompt.objects.get(user=owner, name="styrkor_utveckling_risk").text
                    context["sur_text"] = _run_openai(
                        P,
                        style,
                        tq_fardighet_text=context["tq_fardighet_text"],
                        tq_motivation_text=context["tq_motivation_text"],
                        leda_text=context["leda_text"],
                        mod_text=context["mod_text"],
                        sjalkannedom_text=context["sjalkannedom_text"],
                        strategi_text=context["strategi_text"],
                        kommunikation_text=context["kommunikation_text"],
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 8

            # 8 -> 9: Sammanfattande slutsats
            elif step == 8:
                if not context["slutsats_text"]:
                    P = Prompt.objects.get(user=owner, name="sammanfattande_slutsats").text
                    context["slutsats_text"] = _run_openai(
                        P,
                        style,
                        sur_text=context["sur_text"],
                        tq_fardighet_text=context["tq_fardighet_text"],
                        tq_motivation_text=context["tq_motivation_text"],
                        leda_text=context["leda_text"],
                        mod_text=context["mod_text"],
                        sjalkannedom_text=context["sjalkannedom_text"],
                        strategi_text=context["strategi_text"],
                        kommunikation_text=context["kommunikation_text"],
                        uploaded_files=_trim(context.get("uploaded_files_markdown") or
                                             context.get("uploaded_files_text", "")),
                        candidate_name=context["candidate_name"],
                        candidate_role=context["candidate_role"],
                    )
                step = 9

            # 9 -> 10: Sammanställning (ingen AI)
            elif step == 9:
                step = 10

        context["step"] = step

    # ---------- 5) Förbered HTML-versioner till sammanställningen ----------
    context["tq_fardighet_html"] = _markdown_to_html(context.get("tq_fardighet_text", ""))
    context["sur_html"]          = _markdown_to_html(context.get("sur_text", ""))
    context["tq_motivation_html"] = _markdown_to_html(context.get("tq_motivation_text", ""))
    context["leda_html"]         = _markdown_to_html(context.get("leda_text", ""))
    context["mod_html"]          = _markdown_to_html(context.get("mod_text", ""))
    context["sjalkannedom_html"] = _markdown_to_html(context.get("sjalkannedom_text", ""))
    context["strategi_html"]     = _markdown_to_html(context.get("strategi_text", ""))
    context["kommunikation_html"] = _markdown_to_html(context.get("kommunikation_text", ""))
    context["slutsats_html"]     = _markdown_to_html(context.get("slutsats_text", ""))

    # ---------- 6) Render ----------
    return render(request, "index.html", context)



# ====== CHAT HELPERS =========================================================
import chardet
from docx import Document
from PyPDF2 import PdfReader

MAX_FILE_TEXT = 15000  # tecken; vi trimmar för att inte spränga tokens

def _read_file_text(django_file) -> str:
    name = django_file.name.lower()
    try:
        # se till att vi läser från början
        if hasattr(django_file, "open"):
            django_file.open(mode="rb")
        try:
            django_file.seek(0)
        except Exception:
            pass

        if name.endswith(".pdf"):
            reader = PdfReader(django_file)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif name.endswith(".docx"):
            doc = Document(django_file)
            text = "\n".join(p.text for p in doc.paragraphs)
        elif name.endswith((".txt", ".csv", ".md", ".json", ".py", ".html")):
            data = django_file.read()
            enc = chardet.detect(data).get("encoding") or "utf-8"
            text = data.decode(enc, errors="ignore")
        else:
            text = ""

        # CRUCIAL för Postgres: inga NUL-tecken i TextField
        return (text or "").replace("\x00", "")
    except Exception:
        return ""

def _trim_middle(s: str, max_chars: int = MAX_FILE_TEXT) -> str:
    s = s or ""
    if len(s) <= max_chars: 
        return s
    return s[: max_chars//2] + "\n...\n" + s[- max_chars//2 :]

def _build_openai_messages(session):
    """Konstruera historiken som OpenAI-meddelanden."""
    msgs = [{"role":"system","content": session.system_prompt}]
    for m in session.messages.order_by("created_at"):
        msgs.append({"role": m.role, "content": m.content})
    return msgs

# ====== CHAT VIEWS ===========================================================
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.core.files.base import ContentFile
from .models import ChatSession, ChatMessage, ChatAttachment

@login_required
def chat_home(request):
    # skapa session om none
    if request.method == "POST":
        title = request.POST.get("title","Ny chatt").strip() or "Ny chatt"
        s = ChatSession.objects.create(user=request.user, title=title)
        # valfri första system-prompt override
        sp = request.POST.get("system_prompt")
        if sp:
            s.system_prompt = sp
            s.save()
        return redirect("chat_session", session_id=s.id)

    sessions = ChatSession.objects.filter(user=request.user).order_by("-updated_at")
    return render(request, "chat_home.html", {"sessions": sessions})


@login_required
def chat_session(request, session_id):
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    # uppdatera system-prompt/titel
    if request.method == "POST" and "save_settings" in request.POST:
        session.title = request.POST.get("title") or session.title
        session.system_prompt = request.POST.get("system_prompt") or session.system_prompt
        session.save()
        return redirect("chat_session", session_id=session.id)

    # skicka meddelande
    if request.method == "POST" and "send_message" in request.POST:
        user_text = request.POST.get("message", "").strip()
        if user_text or request.FILES:
            # 1) Spara själva user-meddelandet som bara "ren" text (utan utdrag)
            user_msg = ChatMessage.objects.create(session=session, role="user", content=user_text)

            # 2) Spara bilagor + extrahera text (men skriv inte in den i user_msg.content)
            file_texts = []
            for f in request.FILES.getlist("files"):
                att = ChatAttachment(message=user_msg, original_name=f.name)
                att.file.save(f.name, f, save=False)  # spara originalfilen
                att_text = _read_file_text(att.file)  # extrahera text
                att.text_excerpt = _trim_middle(att_text, MAX_FILE_TEXT)
                att.save()

                # bygg endast ett "osynligt" prompt-tillägg till AI (inte till UI)
                if att.text_excerpt:
                    file_texts.append(f"\n--- \nFIL: {att.original_name}\n{att.text_excerpt}")

            # 3) Bygg prompt till OpenAI: ersätt sista user-meddelandet med en version
            #    som inkluderar filtexter, men utan att ändra vad som sparas i DB/UI
            try:
                messages = _build_openai_messages(session)
                combined = user_msg.content
                if file_texts:
                    combined += "\n\n(Bifogade filer – textutdrag, visas ej för användaren)" + "".join(file_texts)
                messages[-1]["content"] = combined  # endast för anropet, ej sparat i DB

                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=1200,
                    temperature=0.3,
                )
                ai_text = resp.choices[0].message.content.strip()
            except Exception as e:
                ai_text = f"(Ett fel inträffade vid AI-anropet: {e})"

            # 4) Spara AI-svaret och bumpa sessionen
            ChatMessage.objects.create(session=session, role="assistant", content=ai_text)
            session.save()
            return redirect("chat_session", session_id=session.id)

    messages = session.messages.order_by("created_at")
    sessions = ChatSession.objects.filter(user=request.user).order_by("-updated_at")[:20]
    return render(
        request,
        "chat_session.html",
        {"session": session, "messages": messages, "sessions": sessions}
    )

@csrf_exempt
@login_required
def chat_send(request, session_id):
    """
    POST: message + files  -> streamar AI-svaret som text/plain.
    Kompatibel med OpenAI Python SDK där man använder create(..., stream=True).
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    if request.method != "POST":
        return StreamingHttpResponse(iter(["Only POST allowed"]), content_type="text/plain; charset=utf-8", status=405)

    user_text = (request.POST.get("message") or "").strip()
    if not user_text and not request.FILES:
        resp = StreamingHttpResponse(iter([""]), content_type="text/plain; charset=utf-8", status=200)
        resp["Cache-Control"] = "no-cache"; resp["X-Accel-Buffering"] = "no"
        return resp

    # 1) Spara user-meddelande (utan filutdrag i content)
    user_msg = ChatMessage.objects.create(session=session, role="user", content=user_text)

    # 2) Filer -> extrahera text -> endast för prompten
    file_texts = []
    for f in request.FILES.getlist("files"):
        att = ChatAttachment(message=user_msg, original_name=f.name)
        att.file.save(f.name, f, save=False)
        att_text = _read_file_text(att.file)
        att.text_excerpt = _trim_middle(att_text, MAX_FILE_TEXT)
        att.save()
        if att.text_excerpt:
            file_texts.append(f"\n--- \nFIL: {att.original_name}\n{att.text_excerpt}")

    # 3) Historik + ersätt sista user content med dold filtext (endast i prompten)
    messages = _build_openai_messages(session)
    combined = user_msg.content
    if file_texts:
        combined += "\n\n(Bifogade filer – textutdrag, visas ej för användaren)" + "".join(file_texts)
    messages[-1]["content"] = combined

    def token_stream():
        pieces = []

        # >>> NYTT: skicka tillbaka bilagelänkar direkt som första rad
        att_links = []
        try:
            # hämta URL + namn från de bilagor vi nyss sparade
            for a in user_msg.attachments.all():
                if a.file and hasattr(a.file, "url"):
                    att_links.append({"name": a.original_name, "url": a.file.url})
        except Exception:
            att_links = []

        # Skicka en kontrollrad som klienten fångar upp (sedan kommer AI-text)
        # Viktigt med newline på slutet, så vi kan särskilja i klienten
        yield "__ATTACH_JSON__" + json.dumps(att_links) + "\n"

        try:
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.3,
                max_tokens=1200,
                stream=True,
            )
            for chunk in stream:
                piece = ""
                try:
                    delta = chunk.choices[0].delta
                    if isinstance(delta, dict):
                        piece = delta.get("content") or ""
                    else:
                        piece = getattr(delta, "content", "") or ""
                except Exception:
                    piece = ""

                if piece:
                    pieces.append(piece)
                    yield piece

        except Exception as e:
            err = f"\n\n(Ett fel inträffade vid AI-anropet: {e})"
            pieces.append(err)
            yield err
        finally:
            ai_text = "".join(pieces).strip()
            ChatMessage.objects.create(session=session, role="assistant", content=ai_text)
            session.save()

    resp = StreamingHttpResponse(token_stream(), content_type="text/plain; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp

@require_POST
@login_required
def chat_delete(request, session_id):
    s = get_object_or_404(ChatSession, id=session_id, user=request.user)
    s.delete()  # Messages/attachments följer med om du har on_delete=CASCADE
    return redirect("chat_home")
