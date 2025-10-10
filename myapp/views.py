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

# ──────────────────────────────────────────────────────────────────────────────
# Miljö
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
if os.path.exists("env.py"):
    import env  # noqa: F401

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ──────────────────────────────────────────────────────────────────────────────
# Defaults: skapas per användare om inget finns
# ──────────────────────────────────────────────────────────────────────────────
def ensure_default_prompts_exist(user):
    if not Prompt.objects.filter(user=user).exists():
        defaults = {
            "testanalys": """Du är en psykolog specialiserad på testtolkning. Nedan finns innehållet från en Excel-rapport med en kandidats testresultat.

Innehållet är rådata från ett Exceldokument. Ditt uppdrag är att:
1. Identifiera siffran i kolumnen "Competency Score: Planning & Organising (STEN)"
2. Identifiera siffran i kolumnen "Competency Score: Adapting to Change (STEN)"
3. Utifrån dessa två värden, skriv en kort reflekterande text (max 5 meningar) om kandidatens administrativa förmåga.

Excelinnehåll:
{excel_text}
""",
            "intervjuanalys": """Du är en HR-expert. Nedan finns intervjuanteckningar. 
Beskriv 3 styrkor och 3 utvecklingsområden. 
Om någon styrka kan bli ett riskbeteende vid press/stress, nämn det.

Anteckningar:
{intervjuanteckningar}
""",
            "helhetsbedomning": """Du är en HR-expert. Nedan finns en testanalys och en intervjusammanfattning. 
Skriv en helhetsbedömning och ange betyg enligt skalan:
- Utrymme för förbättring
- Tillräckligt god förmåga
- God förmåga

Test:
{test_text}

Intervju:
{intervju_text}
"""
        }
        for name, text in defaults.items():
            Prompt.objects.create(user=user, name=name, text=text)

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

    # Behåll tidigare inskickad data även om man bara klickar ett av stegen
    test_text = request.POST.get("test_text", "")
    intervju_text = request.POST.get("intervju_text", "")
    intervju_result = request.POST.get("intervju_result", "")

    context["test_text"] = test_text
    context["intervju_text"] = intervju_text
    context["intervju_result"] = intervju_result

    if request.method == 'POST':
        # ── Steg 1: Excel -> Testanalys ───────────────────────────────────────
        if "excel" in request.FILES:
            try:
                file = request.FILES['excel']
                wb = openpyxl.load_workbook(file)
                ws = wb.active

                output = io.StringIO()
                for row in ws.iter_rows(values_only=True):
                    output.write("\t".join([str(cell) if cell is not None else "" for cell in row]) + "\n")

                excel_text = output.getvalue()
                base_prompt = Prompt.objects.get(user=request.user, name="testanalys").text
                final_prompt = settings.STYLE_INSTRUCTION + "\n\n" + base_prompt.replace("{excel_text}", excel_text)

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": final_prompt}]
                )
                test_text = response.choices[0].message.content.strip()
                context["test_text"] = test_text
            except Exception as e:
                print("OpenAI error (testanalys):", repr(e))
                context["error"] = "Kunde inte hämta testanalys från AI: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 2: Intervju -> Intervjuanalys ───────────────────────────────
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
                context["test_text"] = test_text  # Behåll testtexten också
            except Exception as e:
                print("OpenAI error (intervjuanalys):", repr(e))
                context["error"] = "Kunde inte hämta intervjuanalys från AI: " + str(e)[:500]
                return render(request, "index.html", context)

        # ── Steg 3: Helhetsbedömning + RATINGS_JSON -> Tabell ────────────────
        elif "generate" in request.POST:
            base_prompt = Prompt.objects.get(user=request.user, name="helhetsbedomning").text

            # Trimma långa indata (vanlig kraschorsak)
            tt = _trim(test_text, 6500)
            it = _trim(intervju_text, 6500)

            ratings_instruction = """
---
Nu ska du också leverera en tabellgradering enligt Domarnämndens kravprofil.

Instruktion:
Returnera TVÅ delar i exakt denna ordning:

### RAPPORT
(Skriv helhetsbedömningen enligt tidigare instruktion.)

### RATINGS_JSON
(Returnera ENBART GILTIG JSON utan extra text, enligt följande schema – alla nycklar ska finnas, värden 1–5):

{
  "leda_utveckla_och_engagera": {
    "Leda andra": 1,
    "Engagera andra": 1,
    "Delegera": 1,
    "Utveckla andra": 1
  },
  "mod_och_handlingskraft": {
    "Beslutsamhet": 1,
    "Integritet": 1,
    "Hantera konflikter": 1
  },
  "sjalkannedom_och_emotionell_stabilitet": {
    "Självmedvetenhet": 1,
    "Uthållighet": 1
  },
  "strategiskt_tankande_och_anpassningsformaga": {
    "Strategiskt fokus": 1,
    "Anpassningsförmåga": 1
  },
  "kommunikation_och_samarbete": {
    "Teamarbete": 1,
    "Inflytelserik": 1
  }
}

Skalan (använd i JSON som heltal):
1 = Utrymme för utveckling
2 = Tillräcklig
3 = God
4 = Mycket god
5 = Utmärkt

Basa bedömningen på testanalysen och intervjuanteckningarna ovan.
Ingen extra text i JSON-delen.
"""

            final_prompt = (
                settings.STYLE_INSTRUCTION
                + "\n\n"
                + base_prompt.replace("{test_text}", tt).replace("{intervju_text}", it)
                + "\n"
                + ratings_instruction
            )

            # 1) Primärt anrop: rapport + JSON i ett svar
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": final_prompt}],
                    max_tokens=1400,
                    temperature=0.2
                )
                full = resp.choices[0].message.content.strip()
            except Exception as e:
                print("OpenAI error (helhet primary):", repr(e))
                context["error"] = "Kunde inte skapa helhetsbedömning (primärt anrop): " + str(e)[:500]
                return render(request, "index.html", context)

            # 2) Plocka ut RAPPORT + JSON
            ratings = _safe_json_from_text(full)
            rapport_part = re.split(r"###\s*RATINGS_JSON", full, flags=re.IGNORECASE)[0].strip()
            context["helhetsbedomning"] = markdown2.markdown(rapport_part)

            # 3) Om JSON saknas – backup-anrop som bara returnerar JSON
            if not ratings:
                print("No JSON found – trying compact backup call")
                backup_prompt = textwrap.dedent(f"""
                Returnera ENDAST giltig JSON enligt schemat nedan, utan Markdown-staket och utan extra text.
                Skalan: 1=Utrymme för utveckling, 2=Tillräcklig, 3=God, 4=Mycket god, 5=Utmärkt.
                Bedöm på test + intervju.

                TEST:
                {tt}

                INTERVJU:
                {it}

                SCHEMA:
                {{
                  "leda_utveckla_och_engagera": {{
                    "Leda andra": 3,
                    "Engagera andra": 3,
                    "Delegera": 3,
                    "Utveckla andra": 3
                  }},
                  "mod_och_handlingskraft": {{
                    "Beslutsamhet": 3,
                    "Integritet": 3,
                    "Hantera konflikter": 3
                  }},
                  "sjalkannedom_och_emotionell_stabilitet": {{
                    "Självmedvetenhet": 3,
                    "Uthållighet": 3
                  }},
                  "strategiskt_tankande_och_anpassningsformaga": {{
                    "Strategiskt fokus": 3,
                    "Anpassningsförmåga": 3
                  }},
                  "kommunikation_och_samarbete": {{
                    "Teamarbete": 3,
                    "Inflytelserik": 3
                  }}
                }}
                """).strip()
                try:
                    r2 = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": backup_prompt}],
                        max_tokens=700,
                        temperature=0.1
                    )
                    ratings = json.loads(r2.choices[0].message.content)
                except Exception as e:
                    print("OpenAI error (helhet backup-json):", repr(e))
                    ratings = _default_all_three()  # sista fallback — UI ska aldrig dö

            # 4) Rendera tabellen
            table_html = _ratings_table_html(ratings)
            context["ratings_table_html"] = mark_safe(table_html)

            # 5) Bevara tidigare fält
            context["test_text"] = test_text
            context["intervju_text"] = intervju_text
            context["intervju_result"] = intervju_result

    return render(request, "index.html", context)


# ====== CHAT HELPERS =========================================================
import chardet
from docx import Document
from PyPDF2 import PdfReader

MAX_FILE_TEXT = 15000  # tecken; vi trimmar för att inte spränga tokens

def _read_file_text(django_file) -> str:
    name = django_file.name.lower()
    try:
        if name.endswith(".pdf"):
            reader = PdfReader(django_file)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text
        elif name.endswith(".docx"):
            doc = Document(django_file)
            return "\n".join(p.text for p in doc.paragraphs)
        elif name.endswith((".txt",".csv",".md",".json",".py",".html")):
            data = django_file.read()
            enc = chardet.detect(data).get("encoding") or "utf-8"
            return data.decode(enc, errors="ignore")
        else:
            return ""  # okänd typ -> hoppa text
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
        user_text = request.POST.get("message","").strip()
        if user_text or request.FILES:
            user_msg = ChatMessage.objects.create(session=session, role="user", content=user_text)

            # spara bilagor + extrahera text
            file_texts = []
            for f in request.FILES.getlist("files"):
                att = ChatAttachment.objects.create(
                    message=user_msg,
                    file=f,
                    original_name=f.name
                )
                # Läs om från lagrat filobjekt (säkrast)
                att_text = _read_file_text(att.file)
                att.text_excerpt = _trim_middle(att_text, MAX_FILE_TEXT)
                att.save()
                if att.text_excerpt:
                    file_texts.append(f"\n--- \nFIL: {att.original_name}\n{att.text_excerpt}")

            # bygg prompt (lägg filtexter sist i user-meddelandet)
            if file_texts:
                user_msg.content += "\n\nBifogade filer (textutdrag):" + "".join(file_texts)
                user_msg.save()

            # anropa OpenAI
            try:
                messages = _build_openai_messages(session)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=1200,
                    temperature=0.3,
                )
                ai_text = resp.choices[0].message.content.strip()
            except Exception as e:
                ai_text = f"(Ett fel inträffade vid AI-anropet: {e})"

            ChatMessage.objects.create(session=session, role="assistant", content=ai_text)
            session.save()  # bump updated_at
            return redirect("chat_session", session_id=session.id)

    messages = session.messages.order_by("created_at")
    sessions = ChatSession.objects.filter(user=request.user).order_by("-updated_at")[:20]
    return render(
        request, 
        "chat_session.html", 
        {"session": session, "messages": messages, "sessions": sessions}
    )