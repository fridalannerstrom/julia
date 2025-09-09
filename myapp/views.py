import os
import io
import re
import json
import openpyxl
import markdown2
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.safestring import mark_safe
from dotenv import load_dotenv
from openai import OpenAI
from .models import Prompt
from django.conf import settings

# Ladda miljövariabler
load_dotenv()
if os.path.exists("env.py"):
    import env

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Skapa standardprompter för användaren om de inte finns
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


def build_ratings_table_html(ratings: dict) -> str:
    """
    Bygger en tabelliknande layout (5 kolumner: 1-5) med bock i vald kolumn.
    ratings förväntas vara ett dict enligt schemat i prompten (se generate-steget).
    """
    # Kolumnrubriker enligt Domarnämndens 5-gradiga skala
    headers = ["Utrymme för utveckling", "Tillräcklig", "God", "Mycket god", "Utmärkt"]

    # För att visa i definierad och logisk ordning:
    section_order = [
        ("leda_utveckla_och_engagera", "1. Leda, utveckla och engagera"),
        ("mod_och_handlingskraft", "2. Mod och handlingskraft"),
        ("sjalkannedom_och_emotionell_stabilitet", "3. Självkännedom och emotionell stabilitet"),
        ("strategiskt_tankande_och_anpassningsformaga", "4. Strategiskt tänkande och anpassningsförmåga"),
        ("kommunikation_och_samarbete", "5. Kommunikation och samarbete"),
    ]

    # Hjälprad för en underkategori
    def row_html(name: str, value: int) -> str:
        tds = []
        for col in range(1, 6):
            mark = "✓" if value == col else ""
            tds.append(f'<td class="dn-cell">{mark}</td>')
        return f"""
        <tr>
            <th class="dn-sub">{name}</th>
            {''.join(tds)}
        </tr>"""

    # Bygg tabeller per sektion
    sections_html = []
    for key, title in section_order:
        if key not in ratings:
            continue
        rows = []
        for sub_name, score in ratings[key].items():
            # skydda mot out-of-range
            try:
                val = int(score)
            except Exception:
                val = 3
            val = max(1, min(5, val))
            rows.append(row_html(sub_name, val))

        table_html = f"""
        <div class="dn-section">
          <h3 class="dn-h3">{title}</h3>
          <table class="dn-table">
            <thead>
              <tr>
                <th class="dn-head dn-first"></th>
                {''.join([f'<th class="dn-head">{h}</th>' for h in headers])}
              </tr>
            </thead>
            <tbody>
              {''.join(rows)}
            </tbody>
          </table>
        </div>
        """
        sections_html.append(table_html)

    # Enkel inlined CSS så du slipper röra statiska filer nu
    css = """
    <style>
      .dn-section{margin:24px 0;}
      .dn-h3{font-size:1.1rem;margin-bottom:8px;}
      .dn-table{width:100%;border-collapse:separate;border-spacing:0 6px;}
      .dn-head{font-weight:600;font-size:.9rem;text-align:center;white-space:nowrap;}
      .dn-first{width:32%;}
      .dn-sub{font-weight:600;background:#f7f9fc;padding:10px;border-radius:8px 0 0 8px;}
      .dn-cell{background:#f7f9fc;text-align:center;padding:10px;min-width:110px;border-left:4px solid #fff;}
      .dn-cell:first-of-type{border-left:none;}
      .dn-cell, .dn-sub{border:1px solid #e6ebf2;border-left:0;}
      tr>th.dn-sub + td{border-left:1px solid #e6ebf2;}
      .dn-cell{border-radius:0;}
      tr>td.dn-cell:last-child{border-radius:0 8px 8px 0;}
    </style>
    """
    return css + "\n".join(sections_html)


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
        if "excel" in request.FILES:
            file = request.FILES['excel']
            wb = openpyxl.load_workbook(file)
            ws = wb.active

            output = io.StringIO()
            for row in ws.iter_rows(values_only=True):
                output.write("\t".join([str(cell) if cell is not None else "" for cell in row]) + "\n")

            excel_text = output.getvalue()
            base_prompt = Prompt.objects.get(user=request.user, name="testanalys").text
            final_prompt = settings.STYLE_INSTRUCTION + "\n\n" + base_prompt.replace("{excel_text}", excel_text)

            import ssl
            print("🔒 SSL version:", ssl.OPENSSL_VERSION)
            print("🔑 API key exists?", bool(os.getenv("OPENAI_API_KEY")))
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": final_prompt}]
            )
            test_text = response.choices[0].message.content.strip()
            context["test_text"] = test_text

        elif "intervju" in request.POST:
            intervjuanteckningar = request.POST.get("intervju", "")
            base_prompt = Prompt.objects.get(user=request.user, name="intervjuanalys").text
            final_prompt = settings.STYLE_INSTRUCTION + "\n\n" + base_prompt.replace("{intervjuanteckningar}", intervjuanteckningar)

            import ssl
            print("🔒 SSL version:", ssl.OPENSSL_VERSION)
            print("🔑 API key exists?", bool(os.getenv("OPENAI_API_KEY")))
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": final_prompt}]
            )
            intervju_result = response.choices[0].message.content.strip()
            context["intervju_text"] = intervjuanteckningar
            context["intervju_result"] = intervju_result
            context["test_text"] = test_text  # Behåll testtexten också

        elif "generate" in request.POST:
            base_prompt = Prompt.objects.get(user=request.user, name="helhetsbedomning").text
            # Lägg till en andra del som kräver RATINGS_JSON i Domarnämndens format
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

Underlag att basera bedömningen på: testanalysen och intervjusammanfattningen ovan.
Var konsekvent och realistisk. Ingen extra text i JSON-delen.
"""
            final_prompt = (
                settings.STYLE_INSTRUCTION
                + "\n\n"
                + base_prompt.replace("{test_text}", test_text).replace("{intervju_text}", intervju_text)
                + "\n"
                + ratings_instruction
            )

            import ssl
            print("🔒 SSL version:", ssl.OPENSSL_VERSION)
            print("🔑 API key exists?", bool(os.getenv("OPENAI_API_KEY")))
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": final_prompt}]
            )
            full = response.choices[0].message.content.strip()

            # Dela upp svaret i RAPPORT och RATINGS_JSON
            # 1) Hämta rapportdelen (markdownas som tidigare)
            rapport_part = full
            ratings_json = None

            # Försök plocka ut JSON efter sektionen ### RATINGS_JSON
            m = re.search(r"###\s*RATINGS_JSON\s*(\{.*\})", full, flags=re.DOTALL)
            if m:
                try:
                    ratings_json = json.loads(m.group(1))
                    # Ta bort JSON-delen ur rapporttexten innan vi markdownar
                    rapport_part = full[:m.start()].strip()
                except Exception as e:
                    print("JSON parse error:", e)

            context["helhetsbedomning"] = markdown2.markdown(rapport_part)

            # Bygg och skicka tabell-HTML om vi fick JSON
            if ratings_json:
                table_html = build_ratings_table_html(ratings_json)
                context["ratings_table_html"] = mark_safe(table_html)

            context["test_text"] = test_text
            context["intervju_text"] = intervju_text
            context["intervju_result"] = intervju_result

    return render(request, "index.html", context)
