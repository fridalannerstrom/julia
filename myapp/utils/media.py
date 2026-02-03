import os
from django.conf import settings
from django.utils.text import slugify

def save_report_png(png_bytes: bytes, report_id: int, name: str) -> str:
    """
    Sparar PNG-bytes till MEDIA och returnerar en URL (som du kan stoppa i <img src="...">).
    """
    safe_name = slugify(name) or "image"
    rel_dir = f"reports/{report_id}/tables"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"{safe_name}.png"
    abs_path = os.path.join(abs_dir, filename)

    with open(abs_path, "wb") as f:
        f.write(png_bytes)

    return f"{settings.MEDIA_URL}{rel_dir}/{filename}"
