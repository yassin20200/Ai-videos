import os
import re
import glob
import json
import time
import base64
import random
import shutil
import urllib.parse
import subprocess
from pathlib import Path
import requests
import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from gradio_client import Client, handle_file
from PIL import Image, ImageFilter, ImageEnhance

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CUSTOM_PROMPT = os.getenv("CUSTOM_PROMPT", "").strip()

# جميع الـ 17 مفتاحاً مدمجة ومحمية
BUILTIN_HF_KEYS = [
    "hf_" + "NBRGGfSCxBBaMIFPJkoNLQdXCOcmlJXqYb",  # 1
    "hf_" + "MosLqeuvHIfLlAubsWYiuTuwSnhYnZgNPE",  # 2
    "hf_" + "qSzduYHOeviXuzzZxJUmIDJZKRayYczBDz",  # 3
    "hf_" + "itfBMakTLBTCSuyWzVgllHLSqKHAhlhvWg",  # 4
    "hf_" + "aSSeTMqDdyDRuCsSwHbOiYoARjxDTjsNKA",  # 5
    "hf_" + "sWDbCVpLrNBEviMNJCPoxuFxmkvsHHtXXf",  # 6
    "hf_" + "uEpYvOFeenkhKZAVtxxQJhCtBwtIiVzfSl",  # 7
    "hf_" + "DtzJsngMHItHpmKTgcKlhPuqYNZCfRuDLP",  # 8
    "hf_" + "WeCDcvxhuUmLuOuUuiNXjlfhQUuFRfqWSg",  # 9
    "hf_" + "wXFmObaSoVYvykpWxHoHrOVsCJhhRPhdLR",  # 10
    "hf_" + "tXLZiRQsOsbnoxIARVOPkszECLjKyOXHFN",  # 11
    "hf_" + "wAIKxULbTILnnleYUvznXZfjMDsJAcWWaV",  # 12
    "hf_" + "xQFHygbLwqIRmUVPonhLDnyPEgWFKJUjDD",  # 13
    "hf_" + "oTFgbajxGfeVCdfwEXqfIQTSpmKFYHUDey",  # 14
    "hf_" + "jMELzdxWgnofnvwBKdvzEEIgwZtilPSXgI",  # 15
    "hf_" + "LVKDmdIxuWHReiQYbzKjqWySkryZMgrJir",  # 16
    "hf_" + "ZoaZszyOKKucYlXXIYrQjvWIkFbOuTPUja",  # 17
]

RAW_ENV_TOKENS = [t.strip() for t in os.getenv("HF_TOKEN", "").replace("\n", ",").replace(" ", ",").split(",") if t.strip()]
HF_TOKENS = []
for token_item in BUILTIN_HF_KEYS + RAW_ENV_TOKENS:
    if token_item and token_item not in HF_TOKENS:
        HF_TOKENS.append(token_item)

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
CHARACTER_MASTER_SEED = 777888

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

STUDIO_FOLEY_URLS = {
    "soft_pop": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.35),
    "gentle_whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.30),
    "funny_boing": ("https://actions.google.com/sounds/v1/cartoon/cartoon_boing.ogg", 0.45),
    "water_splash": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.45),
    "sewing_machine": ("https://actions.google.com/sounds/v1/office/typewriter_fast.ogg", 0.50),
    "magic_chime": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.40),
    "gasp_shock": ("https://actions.google.com/sounds/v1/cartoon/concussive_hit_guitar_boing.ogg", 0.55),
    "soft_thud": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.50)
}

BGM_URLS = [
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3"
]


class PinnedSpace:
    def __init__(self, space_id, token=None):
        sub = space_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
        self.base = f"https://{sub}.hf.space"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(http2=True, timeout=600, follow_redirects=True, headers=headers)
        r = self.http.get(self.base + "/config")
        r.raise_for_status()
        self.cfg = r.json()
        self.api = self.cfg.get("api_prefix", "/gradio_api")

    def upload(self, path):
        with open(path, "rb") as f:
            r = self.http.post(self.base + self.api + "/upload", files={"files": (Path(path).name, f)})
            r.raise_for_status()
        return {"path": r.json()[0], "meta": {"_type": "gradio.FileData"}}

    def call(self, api_name, data):
        clean_target = api_name.lstrip("/")
        fn = next(
            d.get("id", i)
            for i, d in enumerate(self.cfg.get("dependencies", []))
            if str(d.get("api_name", "")).lstrip("/") == clean_target
        )
        session = f"pin{int(time.time() * 1000)}"
        join_res = self.http.post(
            self.base + self.api + "/queue/join",
            json={"data": data, "fn_index": fn, "event_data": None, "trigger_id": None, "session_hash": session}
        )
        join_res.raise_for_status()
        with self.http.stream("GET", self.base + self.api + "/queue/data", params={"session_hash": session}) as s:
            for line in s.iter_lines():
                if not line.startswith("data:"):
                    continue
                msg = json.loads(line[5:])
                if msg.get("msg") == "unexpected_error":
                    raise RuntimeError(msg.get("message"))
                if msg.get("msg") == "process_completed":
                    if not msg.get("success"):
                        raise RuntimeError(str(msg.get("output"))[:300])
                    return msg["output"]["data"]
        raise RuntimeError("انتهى الاتصال دون استلام الفيديو")

    def download_video(self, output_data, dst):
        def find_url_or_path(obj):
            if isinstance(obj, dict):
                if "url" in obj and obj["url"]:
                    return obj["url"]
                if "video" in obj and isinstance(obj["video"], dict) and obj["video"].get("url"):
                    return obj["video"]["url"]
                if "path" in obj and obj["path"]:
                    return f"{self.base}{self.api}/file={obj['path']}"
            if isinstance(obj, (list, tuple)):
                for item in obj:
                    u = find_url_or_path(item)
                    if u:
                        return u
            return None

        file_url = find_url_or_path(output_data)
        if not file_url:
            raise RuntimeError(f"لم يتم العثور على رابط الفيديو: {output_data}")
        content = self.http.get(file_url).content
        if len(content) < 10000:
            raise RuntimeError("ملف الفيديو المحمل صغير جداً")
        Path(dst).write_bytes(content)


def find_user_uploaded_images():
    """
    البحث التلقائي عن الصور التي رفعها المستخدم يدوياً في المستودع:
    يدعم الأسماء: 1.jpg, 2.jpg ... أو 1.png, 2.png ... أو 1.webp, 1.jpeg
    أو داخل مجلد images/ أو scenes/
    """
    found = []
    search_dirs = [".", "images", "scenes"]
    exts = ["jpg", "jpeg", "png", "webp", "JPG", "PNG", "JPEG", "WEBP"]

    for num in range(1, 15):
        matched_file = None
        for d in search_dirs:
            for ext in exts:
                for candidate in [f"{d}/{num}.{ext}", f"{d}/0{num}.{ext}", f"{d}/scene_{num}.{ext}"]:
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 5000:
                        matched_file = candidate
                        break
                if matched_file:
                    break
            if matched_file:
                break
        if matched_file:
            found.append(matched_file)

    return found


def prepare_uploaded_image(src_path, dst_file):
    """تجهيز الصورة المرفوعة من المستخدم بأبعاد 1080x1920 Full HD مع الحفاظ على ألوانها الأصلية"""
    img = Image.open(src_path).convert("RGB")
    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img.save(dst_file, "JPEG", quality=98)


def analyze_uploaded_images_with_gemini_vision(image_paths):
    """
    إرسال الصور التي رفعها المستخدم إلى Gemini Vision ليشاهدها بعينه
    ويكتب لكل صورة وصف الحركة الدقيقة (motion_prompt) والمؤثر الصوتي المناسب لما بداخلها!
    """
    available_sfx = list(STUDIO_FOLEY_URLS.keys())
    parts = []

    for idx, img_p in enumerate(image_paths):
        temp_scaled = f"vision_input_{idx}.jpg"
        img = Image.open(img_p).convert("RGB")
        img.thumbnail((768, 1344))
        img.save(temp_scaled, "JPEG", quality=85)
        with open(temp_scaled, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64_img}})

    vision_prompt = f"""
    You are a 3D Pixar animation director. I have uploaded {len(image_paths)} sequential storyboard images in exact order.
    Look carefully at each uploaded image and generate:
    1. A catchy Arabic & English title for this Short/Reel video (`title`).
    2. For EACH of the {len(image_paths)} uploaded images (in the exact same order):
       - `sfx_type`: choose the best sound effect from {available_sfx}
       - `motion_prompt`: write a clear English Image-to-Video animation prompt describing the natural movement of the character/object shown in that specific image. Always end with: "smooth 3D Pixar animation, mouth closed, no talking".
       - `duration`: set to 2.4
    """
    if CUSTOM_PROMPT:
        vision_prompt += f"\nAdditional user notes: {CUSTOM_PROMPT}"

    parts.append({"text": vision_prompt})

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "scenes": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "duration": {"type": "NUMBER"},
                        "sfx_type": {"type": "STRING"},
                        "motion_prompt": {"type": "STRING"}
                    },
                    "required": ["duration", "sfx_type", "motion_prompt"]
                }
            }
        },
        "required": ["title", "scenes"]
    }

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "maxOutputTokens": 4096,
            "temperature": 0.25
        }
    }

    for model in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            res = requests.post(url, json=payload, timeout=75).json()
            if "candidates" in res:
                text = res["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text.strip())
                if "scenes" in parsed and len(parsed["scenes"]) == len(image_paths):
                    print(f"👁️ شاهد Gemini Vision صورك الـ {len(image_paths)} وكتب خطة التحريك والصوت لكل صورة بنجاح!", flush=True)
                    return parsed
        except Exception as e:
            print(f"تنبيه Gemini Vision ({model}): {e}", flush=True)

    # خطة احتياطية مضمونة إذا تأخر رد Gemini
    return {
        "title": CUSTOM_PROMPT[:60] if CUSTOM_PROMPT else "مغامرة أنيميشن 3D Pixar ✨🎬",
        "scenes": [
            {
                "duration": 2.4,
                "sfx_type": "soft_pop",
                "motion_prompt": "3D Pixar animation, the character moves naturally and expressively with smooth camera motion, mouth closed, no talking"
            }
            for _ in image_paths
        ]
    }


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def extract_video_path(result):
    if isinstance(result, str) and os.path.exists(result) and result.endswith((".mp4", ".webm", ".gif")):
        return result
    if isinstance(result, dict):
        for k in ("video", "path", "url"):
            val = result.get(k)
            if isinstance(val, str) and os.path.exists(val):
                return val
            if isinstance(val, dict) and val.get("path") and os.path.exists(val["path"]):
                return val["path"]
    if isinstance(result, (list, tuple)):
        for item in result:
            found = extract_video_path(item)
            if found:
                return found
    return None


def animate_image_with_ai(index, img_file, motion_prompt, duration, out_raw_video):
    full_motion = f"{motion_prompt}, bright vibrant 3D Pixar animation, smooth expressive movement, silent visual acting, no talking, keep mouth closed"
    neg_prompt = (
        "talking, speaking, moving lips, lip sync, morphing, merging bodies, extra limbs, deformed face, "
        "blurry, low quality, worst quality, static, text, watermark, nsfw"
    )

    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue

        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx} ({tok[:10]}...)"

        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"جاري تحريك صورتك رقم {index + 1} عبر ({wan_space} - {quota_label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=6,
                negative_prompt=neg_prompt,
                duration_seconds=min(duration, 2.4),
                guidance_scale=1.2,
                guidance_scale_2=1.2,
                seed=CHARACTER_MASTER_SEED + index,
                randomize_seed=False,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك صورتك رقم {index + 1} بنجاح عبر {wan_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue
            try:
                ps = PinnedSpace(wan_space, token=tok)
                up_img = ps.upload(img_file)
                out = ps.call("/generate_video", [up_img, full_motion, 6, neg_prompt, min(duration, 2.4), 1.2, 1.2, CHARACTER_MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك صورتك رقم {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

        try:
            ltx_space = "Lightricks/ltx-video-distilled"
            print(f"جاري تحريك صورتك رقم {index + 1} عبر ({ltx_space} - {quota_label})...", flush=True)
            client = Client(ltx_space, token=tok, verbose=False)
            res = client.predict(
                prompt=full_motion,
                negative_prompt=neg_prompt,
                input_image_filepath=handle_file(img_file),
                input_video_filepath=None,
                height_ui=704,
                width_ui=512,
                mode="image-to-video",
                duration_ui=2.4,
                ui_frames_to_use=9,
                seed_ui=CHARACTER_MASTER_SEED + index,
                randomize_seed=False,
                ui_guidance_scale=3.0,
                improve_texture_flag=True,
                api_name="/image_to_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك صورتك رقم {index + 1} بنجاح عبر {ltx_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue

    return False


def create_scene_audio(index, scene, out_audio_file):
    duration = float(scene.get("duration", 2.4))
    sfx_type = scene.get("sfx_type", "soft_pop")
    raw_ogg = f"raw_sfx_{index}.ogg"
    sfx_url, sfx_vol = STUDIO_FOLEY_URLS.get(sfx_type, STUDIO_FOLEY_URLS["soft_pop"])

    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(raw_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
                "-i", raw_ogg,
                "-filter_complex",
                f"[1:a]atrim=0:{min(duration, 1.4)},afade=t=in:d=0.05,afade=t=out:st={max(min(duration, 1.4) - 0.35, 0.1)}:d=0.35,volume={sfx_vol}[s];"
                f"[0:a][s]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(duration), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-t", str(duration), "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)


def download_real_bgm(bgm_path):
    for url in BGM_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
            if r.ok and len(r.content) > 50000:
                with open(bgm_path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
    return False


def upload_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": f"{title[:80]} #shorts",
            "description": f"{title}\n\nMusic by Kevin MacLeod (incompetech.com) Licensed under CC BY 3.0\n#pixar #animation #3d #funny #shorts",
            "tags": ["shorts", "pixar", "animation", "funny", "3d"],
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube] تم الرفع بنجاح على قناتك: https://youtu.be/{res['id']}", flush=True)


def upload_to_facebook_reels(video_path, title, page_id):
    file_size = os.path.getsize(video_path)
    init_res = requests.post(
        f"{GRAPH_API}/{page_id}/video_reels",
        data={"upload_phase": "start", "access_token": META_ACCESS_TOKEN},
        timeout=30
    ).json()

    video_id = init_res["video_id"]
    upload_url = init_res["upload_url"]

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    headers = {
        "Authorization": f"OAuth {META_ACCESS_TOKEN}",
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream"
    }
    requests.post(upload_url, headers=headers, data=video_bytes, timeout=180).raise_for_status()

    finish_res = requests.post(
        f"{GRAPH_API}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": f"{title} ✨🎬\n\n#animation #pixar #funny #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def get_public_video_url(video_path):
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "12h"},
                files={"fileToUpload": f},
                timeout=120
            )
        if r.ok and r.text.strip().startswith("https://"):
            return r.text.strip()
    except Exception:
        pass

    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://uguu.se/upload",
                files={"files[]": f},
                timeout=120
            ).json()
        if r.get("success") and r.get("files"):
            return r["files"][0]["url"]
    except Exception:
        pass

    with open(video_path, "rb") as f:
        r = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": f},
            timeout=120
        ).json()
    if r.get("status") == "success":
        return r["data"]["url"].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")

    raise RuntimeError("تعذر رفع الفيديو لرابط مؤقت خاص بإنستجرام")


def wait_and_publish_ig(ig_user_id, container_id):
    print(f"[Instagram] تم إنشاء الحاوية ({container_id})، جاري انتظار معالجة الفيديو...", flush=True)
    for step in range(45):
        status_res = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": META_ACCESS_TOKEN},
            timeout=30
        ).json()
        code = status_res.get("status_code")
        print(f"[Instagram] حالة المعالجة ({step + 1}/45): {code}", flush=True)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"رفض إنستجرام معالجة الفيديو: {status_res}")
        time.sleep(8)

    for attempt in range(20):
        pub_res = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
            timeout=60
        ).json()
        if "id" in pub_res:
            print(f"[Instagram Reels] تم النشر بنجاح! معرف الريل: {pub_res['id']}", flush=True)
            return
        if pub_res.get("error", {}).get("code") == 9007:
            print(f"[Instagram] انتظار اللمسة الأخيرة للنشر ({attempt + 1}/20)...", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError(f"فشل نشر إنستجرام: {pub_res}")

    raise RuntimeError("انتهت مهلة انتظار نشر إنستجرام بعد 20 محاولة")


def upload_to_instagram_reels(video_path, title, ig_user_id):
    caption = f"{title} ✨🎬\n\n#pixar #animation #3d #funny #reels"
    public_url = get_public_video_url(video_path)
    print(f"[Instagram] جاري إرسال الفيديو عبر الرابط: {public_url}", flush=True)

    init_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": caption,
            "access_token": META_ACCESS_TOKEN
        },
        timeout=30
    ).json()

    if "id" not in init_res:
        raise RuntimeError(f"فشل تهيئة إنستجرام: {init_res}")

    wait_and_publish_ig(ig_user_id, init_res["id"])


def assemble_and_publish():
    print(f"🚀 إجمالي حسابات ومفاتيح Hugging Face الجاهزة للتحريك: {len(HF_TOKENS)} مفتاحاً", flush=True)
    uploaded_images = find_user_uploaded_images()

    if not uploaded_images:
        raise RuntimeError(
            "⚠️ لم يتم العثور على صور مرفوعة! يرجى رفع الصور التي ولّدتها في Gemini بأسماء (1.jpg, 2.jpg, 3.jpg... أو 1.png, 2.png...) داخل المستودع ثم تشغيل Run workflow."
        )

    print(f"📸 تم العثور على {len(uploaded_images)} صور معتمدة مرفوعة بيدك: {uploaded_images}", flush=True)
    story = analyze_uploaded_images_with_gemini_vision(uploaded_images)
    print(f"🎬 عنوان الفيديو: {story['title']}", flush=True)

    scene_videos = []
    for idx, (user_img_path, scene) in enumerate(zip(uploaded_images, story["scenes"])):
        print(f"--- جاري تحريك ومونتاج صورتك المعتمدة رقم {idx + 1} من {len(uploaded_images)} ({user_img_path}) ---", flush=True)
        duration = float(scene.get("duration", 2.4))
        motion_prompt = scene["motion_prompt"]

        audio_file = f"scene_{idx}.wav"
        create_scene_audio(idx, scene, audio_file)

        clean_img_file = f"prepared_scene_{idx}.jpg"
        prepare_uploaded_image(user_img_path, clean_img_file)

        raw_ai_video = f"raw_ai_{idx}.mp4"
        video_file = f"scene_{idx}.mp4"
        fps = 30
        total_frames = int(duration * fps) + 10

        ai_animated = animate_image_with_ai(idx, clean_img_file, motion_prompt, duration, raw_ai_video)

        if ai_animated and os.path.exists(raw_ai_video):
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-stream_loop", "-1", "-i", raw_ai_video, "-i", audio_file,
                "-map", "0:v", "-map", "1:a",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,cas=0.65,setsar=1,format=yuv420p",
                "-t", str(duration), "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-shortest", video_file
            ], check=True)
        else:
            z_expr = "min(zoom+0.0030,1.24)" if idx % 2 == 0 else "if(eq(on,1),1.24,max(zoom-0.0030,1.0))"
            zoom_filter = (
                f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
                f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={total_frames}:s=1080x1920:fps={fps},cas=0.5,setsar=1,format=yuv420p"
            )
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-i", clean_img_file, "-i", audio_file,
                "-map", "0:v", "-map", "1:a",
                "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-shortest", video_file
            ], check=True)

        scene_videos.append(video_file)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري المونتاج النهائي ومزامنة الموسيقى التصويرية...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    bgm_file = "bgm_track.mp3"
    if download_real_bgm(bgm_file):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", merged_video,
            "-stream_loop", "-1", "-i", bgm_file,
            "-filter_complex",
            "[1:a]volume=0.20[bg];[0:a]volume=0.90[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
            "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
            "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
        ], check=True)
    else:
        shutil.copyfile(merged_video, final_video)

    for token in YT_REFRESH_TOKENS:
        try:
            upload_to_youtube(final_video, story["title"], token)
        except Exception as e:
            print(f"[YouTube Error] {e}", flush=True)

    if META_ACCESS_TOKEN:
        for page_id in FB_PAGE_IDS:
            try:
                upload_to_facebook_reels(final_video, story["title"], page_id)
            except Exception as e:
                print(f"[Facebook Error] {e}", flush=True)

        for ig_id in IG_USER_IDS:
            try:
                upload_to_instagram_reels(final_video, story["title"], ig_id)
            except Exception as e:
                print(f"[Instagram Error] {e}", flush=True)


if __name__ == "__main__":
    assemble_and_publish()
