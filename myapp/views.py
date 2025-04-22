import os
import io
import fitz  # PyMuPDF för textextraktion
import requests
from django.shortcuts import render
from openai import OpenAI
from dotenv import load_dotenv

# Ladda .env
load_dotenv()
if os.path.exists("env.py"):
    import env

# Initiera OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🧩 1. Ladda upp PDF till PDF.co
def upload_pdf_to_pdfco(pdf_file):
    url = "https://api.pdf.co/v1/file/upload"
    headers = {"x-api-key": os.getenv("PDFCO_API_KEY")}
    files = {"file": pdf_file}

    response = requests.post(url, headers=headers, files=files)
    result = response.json()

    if not result.get("error"):
        return result.get("url")  # URL till uppladdad fil
    else:
        print("Upload Error:", result.get("message"))
        return None

# 🧩 2. Konvertera PDF-URL till PNG-bilder
def convert_pdf_url_to_images(url):
    api_url = "https://api.pdf.co/v1/pdf/convert/to/png"
    headers = {"x-api-key": os.getenv("PDFCO_API_KEY")}
    payload = {
        "url": url,
        "pages": "2-7",  # ✅ Bara sidor 3–8 (hoppar 1–2)
        "async": False
    }

    response = requests.post(api_url, headers=headers, json=payload)
    result = response.json()

    if not result.get("error"):
        return result.get("urls")  # Lista med bild-URL:er
    else:
        print("Conversion Error:", result.get("message"))
        return []

# 🔍 GPT-analys av text
def analyze_traits(text):
    prompt = f"""
Du är en expert på testtolkning för rekrytering. Läs följande text från en kandidats testresultat och bedöm endast två karaktärsdrag:

1. Struktur & disciplin  
2. Anpassningsförmåga

För varje karaktärsdrag, ange:
- Ett betyg (välj EN av följande):  
    - 1: God förmåga  
    - 2: Tillräckligt god förmåga  
    - 3: Utrymme för förbättring  
- En kort motivering baserad på vad du läser i texten.

Här är testtexten:
{text}

Returnera svaret strukturerat, t.ex.:
---
Struktur & disciplin: Tillräckligt god förmåga  
Motivering: …

Anpassningsförmåga: God förmåga  
Motivering: …
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=500,
    )

    return response.choices[0].message.content.strip()

def analyze_scales_from_images(image_urls):
    prompt = """
Du ser en eller flera bilder från ett personlighetstest.

Varje karaktärsdrag har en visuell skala med 10 rutor i rad från vänster till höger:
- Varje färgad (lila) ruta räknas som 1 poäng
- 10 rutor = maxpoäng (10), 1 ruta = lägsta poäng (1)
- Räkna de färgade rutorna och avgör individens poäng

Du ska:
1. Identifiera namnet på varje skala (står direkt ovanför eller bredvid raderna med rutor)
2. Räkna exakt hur många rutor är färgade
3. Presentera svaret i **en tabell med två kolumner**: "Skala" och "Poäng"

Obs: Ignorera all text till vänster och höger – titta endast på skalanamnet och antalet färgade rutor i rad.

Exempel:
| Skala          | Poäng |
|----------------|-------|
| Empati         | 7     |
| Struktur       | 5     |
"""

    # Lägg till alla bilder som image inputs
    images = [{"type": "image_url", "image_url": {"url": img}} for img in image_urls]

    # Kombinera prompt + bilder
    content = [{"type": "text", "text": prompt}] + images

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        max_tokens=1000,
    )

    return response.choices[0].message.content.strip()

# 🌐 Huvudvy
def index(request):
    result = None
    analysis = None
    pdf_image_urls = []

    if request.method == 'POST' and request.FILES.get('pdf'):
        pdf_file = request.FILES['pdf']
        pdf_bytes = pdf_file.read()

        # ➕ Extrahera text (hoppa första 2 sidor)
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            result = ""
            for page_number in range(2, len(doc)):
                result += doc[page_number].get_text()

        # ➕ GPT-analys
        analysis = analyze_traits(result)

        # ➕ PDF.co: ladda upp + konvertera
        pdf_file.seek(0)  # reset efter read()
        uploaded_url = upload_pdf_to_pdfco(pdf_file)
        if uploaded_url:
            pdf_image_urls = convert_pdf_url_to_images(uploaded_url)

    vision_result = None
    if pdf_image_urls:
        vision_result = analyze_scales_from_images(pdf_image_urls)

    return render(request, 'index.html', {
        'result': result,
        'analysis': analysis,
        'pdf_images': pdf_image_urls,
        'vision_table': vision_result,
    })

