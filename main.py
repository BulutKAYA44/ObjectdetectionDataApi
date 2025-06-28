from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse
from google.cloud import storage
from datetime import timedelta
import uuid, os, json
from typing import List,Optional
from google.oauth2 import service_account
from fastapi import Query
from fastapi.responses import FileResponse
# Cloud Storage bucket adı
BUCKET_NAME = "objectdetection_my-image-bucket"

# Uygulama
app = FastAPI()

# COCO JSON dosyasını tutacağımız klasör (GCS yerine lokalde tutabilirsin istersen)
ANNOTATIONS_DIR = "annotations"
os.makedirs(ANNOTATIONS_DIR, exist_ok=True)
ANNOTATIONS_FILE = os.path.join(ANNOTATIONS_DIR, "annotations.json")

# Eğer yoksa COCO formatında boş şablon oluştur
if not os.path.exists(ANNOTATIONS_FILE):
    with open(ANNOTATIONS_FILE, "w") as f:
        json.dump({
            "images": [],
            "annotations": [],
            "categories": []  # {"id": 1, "name": "limon"} gibi girilecek
        }, f)

@app.post("/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...), metadata: str = Form(...)):
    try:
        # GCS erişimi
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        # Görseli GCS'ye yükle
        ext = os.path.splitext(file.filename)[-1]
        image_id = str(uuid.uuid4())
        blob_name = f"{image_id}{ext}"
        blob = bucket.blob(blob_name)
        blob.upload_from_file(file.file, content_type=file.content_type)
        image_url = blob.generate_signed_url(expiration=timedelta(minutes=60))

        # JSON metadata'yı al
        data = json.loads(metadata)
        category = data["category"]
        bbox = data["bbox"]  # [x, y, width, height]

        # Annotations JSON'u yükle
        with open(ANNOTATIONS_FILE, "r") as f:
            coco_data = json.load(f)

        # Kategori ID'si bul veya oluştur
        existing = next((c for c in coco_data["categories"] if c["name"] == category), None)
        if existing:
            category_id = existing["id"]
        else:
            category_id = len(coco_data["categories"]) + 1
            coco_data["categories"].append({"id": category_id, "name": category})

        # image entry
        coco_data["images"].append({
            "id": image_id,
            "file_name": blob_name,
            "width": 640,     # İstersen client'tan gönder
            "height": 480
        })

        # annotation entry
        annotation_id = len(coco_data["annotations"]) + 1
        coco_data["annotations"].append({
            "id": annotation_id,
            "image_id": image_id,
            "category_id": category_id,
            "bbox": bbox,
            "area": bbox[2] * bbox[3],
            "iscrowd": 0
        })

        # JSON'u kaydet
        with open(ANNOTATIONS_FILE, "w") as f:
            json.dump(coco_data, f, indent=2)

        return {
            "message": "Uploaded and annotated",
            "filename": blob_name,
            "image_url": image_url,
            "category": category,
            "bbox": bbox
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


@app.get("/dataset")
async def get_coco_dataset(
    category: Optional[str] = Query(None, description="Kategoriye göre filtre (örnek: limon)"),
    count: Optional[int] = Query(None, description="Kaç adet veri döndürülsün (opsiyonel)")
):
    try:
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        # COCO JSON oku
        with open(ANNOTATIONS_FILE, "r") as f:
            coco_data = json.load(f)

        # Kategori filtrelemesi (eğer istendiyse)
        if category:
            # İlgili kategori ID'yi bul
            cat = next((c for c in coco_data["categories"] if c["name"] == category), None)
            if not cat:
                return JSONResponse(status_code=404, content={"error": "Kategori bulunamadı"})
            cat_id = cat["id"]

            # O kategoriye ait annotationları filtrele
            annotations = [a for a in coco_data["annotations"] if a["category_id"] == cat_id]
            image_ids = list({a["image_id"] for a in annotations})
            images = [i for i in coco_data["images"] if i["id"] in image_ids]
            categories = [cat]
        else:
            annotations = coco_data["annotations"]
            images = coco_data["images"]
            categories = coco_data["categories"]

        # count varsa truncate et
        if count:
            images = images[:count]
            image_ids = set(i["id"] for i in images)
            annotations = [a for a in annotations if a["image_id"] in image_ids]

        # Signed URL'leri ekle
        for img in images:
            blob = bucket.blob(img["file_name"])
            signed_url = blob.generate_signed_url(expiration=timedelta(minutes=60))
            img["signed_url"] = signed_url

        return {
            "images": images,
            "annotations": annotations,
            "categories": categories
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})