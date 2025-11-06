import os
import io
import re
import json
import textwrap
import openpyxl
import markdown2
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

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# ── NYTT: liten wrapper för OpenAI-anrop per rubrik ───────────────────────────
def _run_openai(prompt_text: str, style: str, **vars_) -> str:
    # säkra ersättningar – bara våra två taggar
    pt = prompt_text.replace("{excel_text}", vars_.get("excel_text", ""))
    pt = pt.replace("{intervju_text}", vars_.get("intervju_text", ""))
    filled = (style or "") + "\n\n" + pt
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": filled}],
        temperature=0.2,
        max_tokens=900,
    )
    return (resp.choices[0].message.content or "").strip()

# ── NYTT: gör _ratings_table_html konfigurerbar (header av/på) ───────────────
def _ratings_table_html(ratings: dict, show_headers: bool = True) -> str:
    headers = ["Utrymme för utveckling", "Tillräcklig", "God", "Mycket god", "Utmärkt"]
    section_order = [
        ("leda_utveckla_och_engagera", "1. Leda, utveckla och engagera"),
        ("mod_och_handlingskraft", "2. Mod och handlingskraft"),
        ("sjalkannedom_och_emotionell_stabilitet", "3. Självkännedom och emotionell stabilitet"),
        ("strategiskt_tankande_och_anpassningsformaga", "4. Strategiskt tänkande och anpassningsförmåga"),
        ("kommunikation_och_samarbete", "5. Kommunikation och samarbete"),
    ]

    def row(name, val):
        tds = "".join(f'<td class="dn-cell">{"✓" if val == i else ""}</td>' for i in range(1, 6))
        return f'<tr><th class="dn-sub">{name}</th>{tds}</tr>'

    sections = []
    for key, title in section_order:
        if key not in ratings:
            continue

        rows = []
        for sub, score in ratings[key].items():
            try:
                v = int(score)
            except Exception:
                v = 3
            v = max(1, min(5, v))
            rows.append(row(sub, v))

        # ✅ fix: bygg header-celler separat, undvik inbäddad f-string
        if show_headers:
            header_cells = "".join([f"<th class='dn-head'>{h}</th>" for h in headers])
            thead_html = f"<thead><tr><th class='dn-head dn-first'></th>{header_cells}</tr></thead>"
        else:
            thead_html = "<thead></thead>"

        sections.append(f"""
        <div class="dn-section">
          <h3 class="dn-h3">{title}</h3>
          <table class="dn-table">
            {thead_html}
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>""")

    css = """
    <style>
      .dn-section{margin:24px 0;}
      .dn-h3{font-size:1.1rem;margin-bottom:8px;}
      .dn-table{width:100%;border-collapse:separate;border-spacing:0 6px;}
      .dn-head{font-weight:600;font-size:.9rem;text-align:center;white-space:nowrap;}
      .dn-first{width:32%;}
      .dn-sub{font-weight:600;background:#f7f9fc;padding:10px;border-radius:8px 0 0 8px;}
      .dn-cell{background:#f7f9fc;text-align:center;padding:10px;min-width:110px;
               border-left:4px solid #fff;border:1px solid #e6ebf2;border-left:0;}
      tr>th.dn-sub + td{border-left:1px solid #e6ebf2;}
      tr>td.dn-cell:last-child{border-radius:0 8px 8px 0;}
    </style>"""
    return css + "\n".join(sections)


# ── NYTT: statisk skalförklaring (HTML) med header ───────────────────────────
def _scale_demo_html() -> str:
    demo = {
        "leda_utveckla_och_engagera": {"Exempel": 3},
        "mod_och_handlingskraft": {"Exempel": 3},
        "sjalkannedom_och_emotionell_stabilitet": {"Exempel": 3},
        "strategiskt_tankande_och_anpassningsformaga": {"Exempel": 3},
        "kommunikation_och_samarbete": {"Exempel": 3},
    }
    return _ratings_table_html(demo, show_headers=True)


# ──────────────────────────────────────────────────────────────────────────────
# Defaults: skapas per användare om inget finns
# ──────────────────────────────────────────────────────────────────────────────
def ensure_default_prompts_exist(user):
    defaults = {
        # befintliga
        "testanalys": """Du är en psykolog specialiserad på testtolkning...
{excel_text}
""",
        "intervjuanalys": """Du är en HR-expert...
{intervjuanteckningar}
""",
        "helhetsbedomning": """Du är en HR-expert...
Test:
{test_text}

Intervju:
{intervju_text}
""",
        # nya per-rubrik
        "tq_fardighet": "Skriv TQ Färdighet baserat på testdata.\n\n{excel_text}\n\n(Intervju, om finns)\n{intervju_text}",
        "tq_motivation": "Identifiera de tre främsta motivationsfaktorerna och beskriv kort.\n\n{excel_text}\n\n{intervju_text}",
        "leda": "Skriv bedömning för 'Leda, utveckla och engagera' med fokus på testdata och komplettera med intervju.\n\n{excel_text}\n\n{intervju_text}",
        "mod": "Skriv bedömning för 'Mod och handlingskraft'.\n\n{excel_text}\n\n{intervju_text}",
        "sjalkannedom": "Skriv bedömning för 'Självkännedom och emotionell stabilitet'.\n\n{excel_text}\n\n{intervju_text}",
        "strategi": "Skriv bedömning för 'Strategiskt tänkande och anpassningsförmåga'.\n\n{excel_text}\n\n{intervju_text}",
        "kommunikation": "Skriv bedömning för 'Kommunikation och samarbete'.\n\n{excel_text}\n\n{intervju_text}",
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

def _ratings_table_html(ratings: dict) -> str:
    """Bygger en tabelliknande layout (5 kolumner: 1–5) med bock i vald kolumn."""
    headers = ["Utrymme för utveckling", "Tillräcklig", "God", "Mycket god", "Utmärkt"]
    section_order = [
        ("leda_utveckla_och_engagera", "1. Leda, utveckla och engagera"),
        ("mod_och_handlingskraft", "2. Mod och handlingskraft"),
        ("sjalkannedom_och_emotionell_stabilitet", "3. Självkännedom och emotionell stabilitet"),
        ("strategiskt_tankande_och_anpassningsformaga", "4. Strategiskt tänkande och anpassningsförmåga"),
        ("kommunikation_och_samarbete", "5. Kommunikation och samarbete"),
    ]

    def row(name, val):
        tds = "".join(f'<td class="dn-cell">{"✓" if val==i else ""}</td>' for i in range(1,6))
        return f'<tr><th class="dn-sub">{name}</th>{tds}</tr>'

    sections = []
    for key, title in section_order:
        if key not in ratings:
            continue
        rows = []
        for sub, score in ratings[key].items():
            try:
                v = int(score)
            except Exception:
                v = 3
            v = max(1, min(5, v))
            rows.append(row(sub, v))
        sections.append(f"""
        <div class="dn-section">
          <h3 class="dn-h3">{title}</h3>
          <table class="dn-table">
            <thead>
              <tr>
                <th class="dn-head dn-first"></th>
                {''.join(f'<th class="dn-head">{h}</th>' for h in headers)}
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>""")

    css = """
    <style>
      .dn-section{margin:24px 0;}
      .dn-h3{font-size:1.1rem;margin-bottom:8px;}
      .dn-table{width:100%;border-collapse:separate;border-spacing:0 6px;}
      .dn-head{font-weight:600;font-size:.9rem;text-align:center;white-space:nowrap;}
      .dn-first{width:32%;}
      .dn-sub{font-weight:600;background:#f7f9fc;padding:10px;border-radius:8px 0 0 8px;}
      .dn-cell{background:#f7f9fc;text-align:center;padding:10px;min-width:110px;
               border-left:4px solid #fff;border:1px solid #e6ebf2;border-left:0;}
      tr>th.dn-sub + td{border-left:1px solid #e6ebf2;}
      tr>td.dn-cell:last-child{border-radius:0 8px 8px 0;}
    </style>"""
    return css + "\n".join(sections)

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

# ──────────────────────────────────────────────────────────────────────────────
# Prompt Editor (om du har en sida för att redigera prompter)
# ──────────────────────────────────────────────────────────────────────────────
@login_required
@csrf_exempt
def prompt_editor(request):
    ensure_default_prompts_exist(request.user)
    prompts = Prompt.objects.filter(user=request.user)

    if request.method == "POST":
        if "reset" in request.POST:
            name = request.POST["reset"]
            defaults = {
                "testanalys": """Du är en psykolog specialiserad på testtolkning...""",
                "intervjuanalys": """Du är en HR-expert. Nedan finns intervjuanteckningar...""",
                "helhetsbedomning": """Du är en HR-expert. Nedan finns en testanalys..."""
            }
            if name in defaults:
                prompt = Prompt.objects.get(user=request.user, name=name)
                prompt.text = defaults[name]
                prompt.save()
        else:
            for prompt in prompts:
                field_name = f"prompt_{prompt.name}"
                new_text = request.POST.get(field_name)
                if new_text is not None:
                    prompt.text = new_text
                    prompt.save()

    return render(request, "prompt_editor.html", {"prompts": prompts})

# ──────────────────────────────────────────────────────────────────────────────
# Huvudvy
# ──────────────────────────────────────────────────────────────────────────────
@login_required
@csrf_exempt
def index(request):
    ensure_default_prompts_exist(request.user)
    context = {}

    # ── Hämta befintliga fält från POST så allt bärs mellan steg ──────────────
    # Basfält (din gamla)
    test_text = request.POST.get("test_text", "")
    intervju_text = request.POST.get("intervju_text", "")
    intervju_result = request.POST.get("intervju_result", "")

    # Nya 7 sektioner
    for key, _title in SECTION_KEYS:
        context[key] = request.POST.get(key, "")

    # Sammanställningar
    sur_text = request.POST.get("sur_text", "")
    slutsats_text = request.POST.get("slutsats_text", "")

    context.update({
        "test_text": test_text,
        "intervju_text": intervju_text,
        "intervju_result": intervju_result,
        "sur_text": sur_text,
        "slutsats_text": slutsats_text,
    })

    if request.method == 'POST':
        # ── Steg 1: Excel -> generera 7 sektioner ─────────────────────────────
        if "excel" in request.FILES:
            try:
                file = request.FILES['excel']
                wb = openpyxl.load_workbook(file)
                ws = wb.active
                output = io.StringIO()
                for row in ws.iter_rows(values_only=True):
                    output.write("\t".join([str(cell) if cell is not None else "" for cell in row]) + "\n")
                excel_text = output.getvalue()

                # Spara rå testtext (valfritt att visa)
                context["test_text"] = excel_text

                # Hämta prompter per fält
                P = {p.name: p.text for p in Prompt.objects.filter(user=request.user)}

                # Kör rubrikvis (intervju tom i detta skede)
                kwargs = dict(excel_text=_trim(excel_text), intervju_text=_trim(""))
                context["tq_fardighet_text"] = _run_openai(P["tq_fardighet"], settings.STYLE_INSTRUCTION, **kwargs)
                context["tq_motivation_text"] = _run_openai(P["tq_motivation"], settings.STYLE_INSTRUCTION, **kwargs)
                context["leda_text"] = _run_openai(P["leda"], settings.STYLE_INSTRUCTION, **kwargs)
                context["mod_text"] = _run_openai(P["mod"], settings.STYLE_INSTRUCTION, **kwargs)
                context["sjalkannedom_text"] = _run_openai(P["sjalkannedom"], settings.STYLE_INSTRUCTION, **kwargs)
                context["strategi_text"] = _run_openai(P["strategi"], settings.STYLE_INSTRUCTION, **kwargs)
                context["kommunikation_text"] = _run_openai(P["kommunikation"], settings.STYLE_INSTRUCTION, **kwargs)

            except Exception as e:
                context["error"] = "Kunde inte skapa rubriktexter från Excel: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 2: Intervju -> uppdatera 7 sektioner (om man vill) ──────────
        elif "intervju" in request.POST:
            try:
                intervjuanteckningar = request.POST.get("intervju", "")
                base_prompt = Prompt.objects.get(user=request.user, name="intervjuanalys").text
                final_prompt = settings.STYLE_INSTRUCTION + "\n\n" + base_prompt.replace("{intervjuanteckningar}", intervjuanteckningar)
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": final_prompt}]
                )
                intervju_result = response.choices[0].message.content.strip()
                context["intervju_text"] = intervjuanteckningar
                context["intervju_result"] = intervju_result

                # Uppdatera 7 fält med intervju som extra signal
                P = {p.name: p.text for p in Prompt.objects.filter(user=request.user)}
                kwargs = dict(excel_text=_trim(context.get("test_text","")), intervju_text=_trim(intervjuanteckningar))
                for key, name in [
                    ("tq_fardighet_text","tq_fardighet"),
                    ("tq_motivation_text","tq_motivation"),
                    ("leda_text","leda"),
                    ("mod_text","mod"),
                    ("sjalkannedom_text","sjalkannedom"),
                    ("strategi_text","strategi"),
                    ("kommunikation_text","kommunikation"),
                ]:
                    # bara om användaren inte redan manuellt redigerat (valfritt beteende)
                    if not context.get(key):
                        context[key] = _run_openai(P[name], settings.STYLE_INSTRUCTION, **kwargs)

            except Exception as e:
                context["error"] = "Kunde inte hämta intervjuanalys: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 3a: Generera Styrkor/Utvecklingsområden/Risk ───────────────
        elif "gen_sur" in request.POST:
            try:
                P = Prompt.objects.get(user=request.user, name="styrkor_utveckling_risk").text
                sur = _run_openai(
                    P, settings.STYLE_INSTRUCTION,
                    tq_fardighet_text=context.get("tq_fardighet_text",""),
                    tq_motivation_text=context.get("tq_motivation_text",""),
                    leda_text=context.get("leda_text",""),
                    mod_text=context.get("mod_text",""),
                    sjalkannedom_text=context.get("sjalkannedom_text",""),
                    strategi_text=context.get("strategi_text",""),
                    kommunikation_text=context.get("kommunikation_text",""),
                )
                context["sur_text"] = sur
            except Exception as e:
                context["error"] = "Kunde inte skapa Styrkor/Utvecklingsområden/Risk: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 3b: Generera Sammanfattande slutsats ────────────────────────
        elif "gen_slutsats" in request.POST:
            try:
                P = Prompt.objects.get(user=request.user, name="sammanfattande_slutsats").text
                sl = _run_openai(
                    P, settings.STYLE_INSTRUCTION,
                    sur_text=context.get("sur_text",""),
                    tq_fardighet_text=context.get("tq_fardighet_text",""),
                    tq_motivation_text=context.get("tq_motivation_text",""),
                    leda_text=context.get("leda_text",""),
                    mod_text=context.get("mod_text",""),
                    sjalkannedom_text=context.get("sjalkannedom_text",""),
                    strategi_text=context.get("strategi_text",""),
                    kommunikation_text=context.get("kommunikation_text",""),
                )
                context["slutsats_text"] = sl
            except Exception as e:
                context["error"] = "Kunde inte skapa Sammanfattande slutsats: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 4: Helhetsbedömning + RATINGS_JSON (behåll din logik) ───────
        elif "generate" in request.POST:
            # Din befintliga helhetsbedömning kör vi vidare…
            # (oförändrat, förkortat här för tydlighet)
            # ...
            # Efter att du skapat ratings:
            table_html_no_header = _ratings_table_html(ratings, show_headers=False)
            context["ratings_table_html"] = mark_safe(table_html_no_header)
            context["ratings_scale_demo_html"] = mark_safe(_scale_demo_html())

        # ── Steg 5: Skapa dokument (DOCX) ────────────────────────────────────
        elif "build_doc" in request.POST:
            from docx import Document
            from docx.shared import Pt
            from django.http import HttpResponse

            doc = Document()
            def H(txt): 
                p = doc.add_heading(txt, level=1); return p
            def P(txt):
                if not txt: txt = ""
                para = doc.add_paragraph(txt); para.style.font.size = Pt(11)

            # 1) Skalförklaring
            H("Beskrivning av poängskala")
            P("1 = Utrymme för utveckling · 2 = Tillräcklig · 3 = God · 4 = Mycket god · 5 = Utmärkt")
            # (Enkel tabellrendering – kan göras snyggare)
            demo = {
                "leda_utveckla_och_engagera": {"Exempel": 3},
                "mod_och_handlingskraft": {"Exempel": 3},
                "sjalkannedom_och_emotionell_stabilitet": {"Exempel": 3},
                "strategiskt_tankande_och_anpassningsformaga": {"Exempel": 3},
                "kommunikation_och_samarbete": {"Exempel": 3},
            }
            t = doc.add_table(rows=1, cols=6)
            hdr = t.rows[0].cells
            hdr[0].text = ""
            for i, lab in enumerate(["Utveckling","Tillr.","God","Mycket god","Utmärkt"], start=1):
                hdr[i].text = lab

            # 2) TQ Färdighet
            H("TQ Färdighet"); P(context.get("tq_fardighet_text",""))

            # 3) Styrkor/Utvecklingsområden/Risk
            H("Styrkor, utvecklingsområden, riskbeteenden"); P(context.get("sur_text",""))

            # 4) Motivation
            H("Definition av kandidatens 3 främsta motivationsfaktorer"); P(context.get("tq_motivation_text",""))

            # 5–9) Sektioner (enkelt – utan tabeller här för korthet)
            H("Leda, utveckla och engagera"); P(context.get("leda_text",""))
            H("Mod och handlingskraft"); P(context.get("mod_text",""))
            H("Självkännedom och emotionell stabilitet"); P(context.get("sjalkannedom_text",""))
            H("Strategiskt tänkande och anpassningsförmåga"); P(context.get("strategi_text",""))
            H("Kommunikation och samarbete"); P(context.get("kommunikation_text",""))

            # 10) Sammanfattande slutsats
            H("Sammanfattande slutsats"); P(context.get("slutsats_text",""))

            # Svar som docx
            bio = io.BytesIO()
            doc.save(bio); bio.seek(0)
            resp = HttpResponse(bio.getvalue(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            resp["Content-Disposition"] = 'attachment; filename="rapport.docx"'
            return resp

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
