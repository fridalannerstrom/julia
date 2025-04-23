from google.cloud import vision
from google.oauth2 import service_account
import os

# Ladda .env
if os.path.exists("env.py"):
    import env

# Sätt credentials om inte redan satt
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-vision-key.json"

# Autentisera
credentials = service_account.Credentials.from_service_account_file(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
)
client = vision.ImageAnnotatorClient(credentials=credentials)

# Bildsökväg
image_path = "static/example-report.png"

# Läs in bilden
with open(image_path, "rb") as image_file:
    content = image_file.read()
image = vision.Image(content=content)

# 📄 Textigenkänning istället för object_localization
response = client.text_detection(image=image)
texts = response.text_annotations

# 🔍 Skriv ut resultat
if texts:
    print("💬 Text hittad i bilden:\n")
    print(texts[0].description)  # Detta är hela texten i bilden
else:
    print("❌ Ingen text hittad.")