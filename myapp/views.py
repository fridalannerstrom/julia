# views.py
import os
import openpyxl
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from openai import OpenAI
import io
import markdown2
from .models import Prompt

# Ladda .env
load_dotenv()
if os.path.exists("env.py"):
    import env

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Körs endast om en prompt inte redan finns – skriver INTE över text
def ensure_default_prompts_exist():
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
        Prompt.objects.get_or_create(name=name, defaults={"text": text})

@csrf_exempt
def prompt_editor(request):
    ensure_default_prompts_exist()
    prompts = Prompt.objects.all()

    if request.method == "POST":
        for prompt in prompts:
            field_name = f"prompt_{prompt.name}"
            new_text = request.POST.get(field_name)
            if new_text is not None:
                prompt.text = new_text
                prompt.save()

    return render(request, "prompt_editor.html", {"prompts": prompts})

@csrf_exempt
def index(request):
    ensure_default_prompts_exist()
    context = {}

    if request.method == 'POST':
        if "excel" in request.FILES:
            file = request.FILES['excel']
            wb = openpyxl.load_workbook(file)
            ws = wb.active

            output = io.StringIO()
            for row in ws.iter_rows(values_only=True):
                output.write("\t".join([str(cell) if cell is not None else "" for cell in row]) + "\n")

            excel_text = output.getvalue()

            base_prompt = Prompt.objects.get(name="testanalys").text
            prompt = base_prompt.replace("{excel_text}", excel_text)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            context["test_text"] = response.choices[0].message.content.strip()

        elif "intervju" in request.POST:
            intervjuanteckningar = request.POST.get("intervju")
            base_prompt = Prompt.objects.get(name="intervjuanalys").text
            prompt = base_prompt.replace("{intervjuanteckningar}", intervjuanteckningar)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            context["intervju_text"] = intervjuanteckningar
            context["intervju_result"] = response.choices[0].message.content.strip()
            context["test_text"] = request.POST.get("test_text")

        elif "generate" in request.POST:
            test_text = request.POST.get("test_text")
            intervju_text = request.POST.get("intervju_text")

            base_prompt = Prompt.objects.get(name="helhetsbedomning").text
            prompt = base_prompt.replace("{test_text}", test_text).replace("{intervju_text}", intervju_text)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            context["helhetsbedomning"] = markdown2.markdown(response.choices[0].message.content.strip())
            context["test_text"] = test_text
            context["intervju_text"] = intervju_text
            context["intervju_result"] = request.POST.get("intervju_result", "")

    return render(request, "index.html", context)