from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse
from google.cloud import storage
from datetime import timedelta
import uuid, os, json
from typing import List, Optional
from google.oauth2 import service_account
from PIL import Image

# GCP Bucket
BUCKET_NAME = "objectdetection_my-image-bucket"

app = FastAPI()

@app.post("/upload-image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    metadata: str = Form(...)
):
    try:
        # GCS erişimi
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        # Metadata parse
        data = json.loads(metadata)
        category = data["category"]
        bbox = data["bbox"]

        # Benzersiz dosya ismi
        ext = os.path.splitext(file.filename)[-1]
        image_id = str(uuid.uuid4())
        blob_name = f"{category}/{image_id}{ext}"

        # Dosyayı geçici olarak kaydet
        tmp_path = f"/tmp/{image_id}{ext}"
        with open(tmp_path, "wb") as f_out:
            f_out.write(await file.read())

        # Görüntü boyutu al (PIL ile)
        with Image.open(tmp_path) as img:
            width, height = img.size

        # GCS'ye yükle
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(tmp_path, content_type=file.content_type)
        image_url = blob.generate_signed_url(expiration=timedelta(minutes=60))

        # Annotations dosyasını oku/yarat
        annotation_path = f"{category}/annotations.json"
        annotation_blob = bucket.blob(annotation_path)
        if annotation_blob.exists():
            coco_data = json.loads(annotation_blob.download_as_text())
        else:
            coco_data = {"images": [], "annotations": [], "categories": []}

        # Kategori ID kontrolü
        existing = next((c for c in coco_data["categories"] if c["name"] == category), None)
        if existing:
            category_id = existing["id"]
        else:
            category_id = len(coco_data["categories"]) + 1
            coco_data["categories"].append({"id": category_id, "name": category})

        # Yeni image kaydı
        coco_data["images"].append({
            "id": image_id,
            "file_name": f"{image_id}{ext}",
            "width": width,
            "height": height
        })

        # Yeni annotation kaydı
        annotation_id = len(coco_data["annotations"]) + 1
        coco_data["annotations"].append({
            "id": annotation_id,
            "image_id": image_id,
            "category_id": category_id,
            "bbox": bbox,
            "area": bbox[2] * bbox[3],
            "iscrowd": 0
        })

        # Güncel annotations'ı tekrar GCS'ye yükle
        annotation_blob.upload_from_string(json.dumps(coco_data, indent=2), content_type="application/json")

        return {
            "message": "Uploaded and annotated",
            "filename": blob_name,
            "image_url": image_url,
            "category": category,
            "bbox": bbox,
            "width": width,
            "height": height
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/dataset")
async def get_coco_dataset(
    category: Optional[str] = Query(None, description="Kategori (örnek: limon)")
):
    try:
        key_data = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
        credentials = service_account.Credentials.from_service_account_info(key_data)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)

        if not category:
            return JSONResponse(status_code=400, content={"error": "Kategori parametresi gerekli."})

        annotation_path = f"{category}/annotations.json"
        annotation_blob = bucket.blob(annotation_path)

        if not annotation_blob.exists():
            return JSONResponse(status_code=404, content={"error": "Kategori bulunamadı."})

        annotation_str = annotation_blob.download_as_text()
        coco_data = json.loads(annotation_str)

        # Signed URL ekle
        for img in coco_data["images"]:
            blob = bucket.blob(f"{category}/{img['file_name']}")
            img["signed_url"] = blob.generate_signed_url(expiration=timedelta(minutes=60))

        return coco_data

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
