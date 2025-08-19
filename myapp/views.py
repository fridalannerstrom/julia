import os
import io
import openpyxl
import markdown2
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
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
            final_prompt = settings.STYLE_INSTRUCTION + "\n\n" + base_prompt.replace("{test_text}", test_text).replace("{intervju_text}", intervju_text)

            import ssl
            print("🔒 SSL version:", ssl.OPENSSL_VERSION)
            print("🔑 API key exists?", bool(os.getenv("OPENAI_API_KEY")))
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": final_prompt}]
            )
            context["helhetsbedomning"] = markdown2.markdown(response.choices[0].message.content.strip())
            context["test_text"] = test_text
            context["intervju_text"] = intervju_text
            context["intervju_result"] = intervju_result

    return render(request, "index.html", context)