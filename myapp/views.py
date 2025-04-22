from django.shortcuts import render
from django.http import HttpResponse
import fitz  # PyMuPDF
from django.views.decorators.csrf import csrf_exempt


# Create your views here.
def index(request):
    return render(request, 'index.html')

def index(request):
    result = None

    if request.method == 'POST' and request.FILES.get('pdf'):
        pdf_file = request.FILES['pdf']

        text = ''
        with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()

        result = text  # Här kan vi senare lägga till OpenAI-anrop

    return render(request, 'index.html', {'result': result})