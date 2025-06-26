from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from google.cloud import storage
from datetime import timedelta
import uuid, os
from typing import List
import json
from google.oauth2 import service_account

# GCP servis hesabı json dosyasını göster
#os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_storage_key.json"

# Bucket adı
BUCKET_NAME = "objectdetection_my-image-bucket"

app = FastAPI()


# 📤 RESİM YÜKLEME ENDPOINTİ
@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), category: str = Form(...)):
    try:
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        # Dosya uzantısını koru ve kategori adını ekle
        ext = os.path.splitext(file.filename)[-1]
        blob_name = f"{uuid.uuid4()}_{category}{ext}"
        blob = bucket.blob(blob_name)

        # Yükleme
        blob.upload_from_file(file.file, content_type=file.content_type)

        # Signed URL üret
        signed_url = blob.generate_signed_url(expiration=timedelta(minutes=30))

        return {
            "message": "Uploaded",
            "filename": blob_name,
            "signed_url": signed_url,
            "category": category
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# 📥 KATEGORİYE GÖRE RESİM LİSTELEME ENDPOINTİ
@app.get("/images-by-category")
async def get_images_by_category(
    category: str = Query(..., description="Kategori adı (örnek: cat)"),
    count: int = Query(None, description="İstenilen resim sayısı (opsiyonel)")
):
    try:
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        blobs = list(bucket.list_blobs())

        matched = []
        for blob in blobs:
            # İsimde _category geçiyorsa eşleşir
            if f"_{category}" in blob.name:
                signed_url = blob.generate_signed_url(expiration=timedelta(minutes=30))
                matched.append({
                    "filename": blob.name,
                    "signed_url": signed_url
                })

        # Eğer count verilmişse ilk N tanesini al
        if count:
            matched = matched[:count]

        return {
            "category": category,
            "returned_count": len(matched),
            "images": matched
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
