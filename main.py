import os
import re
import json
import time
import urllib.parse
import subprocess
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"


def generate_story():
    prompt = """
    أنت كاتب محتوى مبدع متخصص في "حواديت الفواكه والخضروات الناطقة" الشهيرة على يوتيوب شورتس وريلز.
    اكتب حدوتة قصيرة ممتعة جداً، طريفة، وذات مغزى جميل (مدتها 40-45 ثانية) تدور أحداثها بين الفواكه أو الخضروات داخل المطبخ أو الثلاجة أو سلة الفواكه (مثل: المانجو، الفراولة، الموزة، التفاحة، الأفوكادو، البطيخة، الليمونة).
    
    القواعد المهمة للقصة:
    1. ابدأ المشهد الأول بجملة خاطفة ومشوقة جداً (Hook) تجذب المشاهد في أول 3 ثوانٍ.
    2. اكتب السرد بأسلوب حكواتي مصري سلس، خفيف الدم، دافئ وممتع جداً للصغار والكبار، مع تشكيل الكلمات لضبط النطق، وبدون أي علامات تنصيص.
    3. اجعل القصة مقسمة إلى 5 مشاهد مترابطة، وكل مشهد بين 15 إلى 22 كلمة.
    4. اجعل وصف الصورة (image_prompt) باللغة الإنجليزية يصف بدقة شخصيات الفواكه الكرتونية المجسمة بأسلوب:
       "Cute 3D Pixar Disney animation style, anthropomorphic talking [fruit name] character with big expressive eyes, cute hands and feet, vibrant colors, cinematic kitchen lighting, 8k, vertical 9:16"
    
    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان جذاب ومشوق للحدوتة بدون علامات تنصيص",
      "scenes": [
        {
          "narration": "النص العربي المشوق للمشهد بدون علامات تنصيص",
          "image_prompt": "Cute 3D Pixar Disney animation style..."
        }
      ]
    }
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    for model in ["gemini-2.5-pro", "gemini-2.5-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        res = requests.post(url, json=payload, timeout=60).json()
        if "candidates" in res:
            print(f"تم تأليف الحدوتة باستخدام: {model}", flush=True)
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    raise RuntimeError(f"فشل الاتصال بـ Gemini API: {res}")


def strip_diacritics(text):
    return re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)


def generate_audio(narration, audio_file):
    clean_text = re.sub(r'["\'«»„“”*]', '', narration).strip()
    plain_text = strip_diacritics(clean_text)

    # استخدام صوت سلمى أو شاكر بنبرة حيوية وممتعة للحدوتة
    attempts = [
        ("ar-EG-SalmaNeural", clean_text),
        ("ar-EG-ShakirNeural", clean_text),
        ("ar-EG-SalmaNeural", plain_text),
        ("ar-EG-ShakirNeural", plain_text)
    ]
    for voice, txt in attempts:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice, "--rate", "+6%",
                "--text", txt, "--write-media", audio_file
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(audio_file) and os.path.getsize(audio_file) > 500:
                print(f"تم توليد الصوت بنجاح ({voice})", flush=True)
                return
        except Exception:
            time.sleep(2)

    print("جاري استخدام البديل الصوتي Google TTS...", flush=True)
    raw_mp3 = f"raw_{audio_file}"
    encoded_text = urllib.parse.quote(plain_text)
    gtts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded_text}"
    r = requests.get(gtts_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    with open(raw_mp3, "wb") as f:
        f.write(r.content)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", raw_mp3,
        "-af", "atempo=1.15", audio_file
    ], check=True)


def download_scene_image(index, image_prompt, img_file):
    # انتظار 6 ثوانٍ لتفادي حظر الطلبات المتتالية وضمان عدم ظهور أي صورة سوداء
    if index > 0:
        time.sleep(6)

    styled_prompt = (
        f"Cute 3D Pixar Disney style animation, {image_prompt[:160]}, "
        f"expressive face, ultra detailed 3d render, vibrant studio lighting, no text"
    )
    encoded_prompt = urllib.parse.quote(styled_prompt)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for attempt, model in enumerate(["flux", "flux", "turbo"]):
        try:
            seed = int(time.time()) + (index * 333) + (attempt * 55)
            img_url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width=1080&height=1920&model={model}&nologo=true&enhance=true&seed={seed}"
            )
            res = requests.get(img_url, headers=headers, timeout=90)
            if res.status_code == 200 and len(res.content) > 12000:
                with open(img_file, "wb") as f:
                    f.write(res.content)
                print(f"تم تصميم صورة المشهد {index + 1} بجودة 3D Pixar", flush=True)
                return
        except Exception as e:
            print(f"إعادة محاولة تحميل صورة المشهد {index + 1}: {e}", flush=True)
        time.sleep(7)

    raise RuntimeError(f"تعذر تحميل صورة المشهد {index + 1} من سيرفر الصور")


def create_scene_assets(index, narration, image_prompt):
    audio_file = f"scene_{index}.mp3"
    generate_audio(narration, audio_file)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, img_file)

    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    # تنويع حركة الكاميرا بين المشاهد (تقريب للمشاهد الزوجية وتبعيد للمشاهد الفردية)
    if index % 2 == 0:
        z_expr = "min(zoom+0.0014,1.25)"
    else:
        z_expr = "if(eq(on,1),1.25,max(zoom-0.0014,1.0))"

    zoom_filter = (
        f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
        f"eq=saturation=1.12:contrast=1.04,"
        f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps},setsar=1,format=yuv420p"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
        "-i", img_file, "-i", audio_file,
        "-vf", zoom_filter, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-t", str(duration), "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-shortest", video_file
    ], check=True)
    return video_file


def upload_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    ch_res = youtube.channels().list(part="snippet", mine=True).execute()
    if ch_res.get("items"):
        ch_title = ch_res["items"][0]["snippet"]["title"]
        ch_id = ch_res["items"][0]["id"]
        print(f"[YouTube] جاري النشر على قناة: {ch_title} ({ch_id})", flush=True)

    body = {
        "snippet": {
            "title": f"{title[:80]} 🍓🥭 #shorts",
            "description": f"{title}\n\n#حواديت #قصص_الفواكه #حدوتة #انيميشن #shorts",
            "tags": ["shorts", "حواديت", "قصص الفواكه", "انيميشن", "حدوتة"],
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube] تم الرفع بنجاح: https://youtu.be/{res['id']}", flush=True)


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
            "description": f"{title} 🍓🍍\n\n#حواديت #قصص_الفواكه #حدوتة #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def get_public_video_url(video_path):
    # المحاولة 1: Litterbox Catbox
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "1h"},
                files={"fileToUpload": f},
                timeout=120
            )
        if r.ok and r.text.strip().startswith("https://"):
            return r.text.strip()
    except Exception as e:
        print(f"تنبيه رفع الرابط الأول: {e}", flush=True)

    # المحاولة 2: Tmpfiles
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
    for _ in range(35):
        status_res = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": META_ACCESS_TOKEN},
            timeout=30
        ).json()
        code = status_res.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"رفض إنستجرام معالجة الفيديو: {status_res}")
        time.sleep(6)

    pub_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
        timeout=60
    ).json()
    print(f"[Instagram Reels] تم النشر بنجاح: {pub_res}", flush=True)


def upload_to_instagram_reels(video_path, title, ig_user_id):
    caption = f"{title} 🍓🥭\n\n#حواديت #قصص_الفواكه #حدوتة #reels"

    # الطريقة الأولى: الرفع عبر رابط مباشر لتخطي خطأ rupload 400
    try:
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
        if "id" in init_res:
            wait_and_publish_ig(ig_user_id, init_res["id"])
            return
    except Exception as e:
        print(f"تنبيه الطريقة الأولى لإنستجرام، جاري التحويل للطريقة المباشرة: {e}", flush=True)

    # الطريقة الثانية الاحتياطية: Resumable Upload بعد ضبط الصيغة القياسية
    file_size = os.path.getsize(video_path)
    init_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "access_token": META_ACCESS_TOKEN
        },
        timeout=30
    ).json()

    if "id" not in init_res:
        raise RuntimeError(f"فشل تهيئة إنستجرام: {init_res}")

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    headers = {
        "Authorization": f"OAuth {META_ACCESS_TOKEN}",
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream"
    }
    up_res = requests.post(init_res["uri"], headers=headers, data=video_bytes, timeout=180)
    if not up_res.ok:
        raise RuntimeError(f"خطأ رفع إنستجرام ({up_res.status_code}): {up_res.text}")

    wait_and_publish_ig(ig_user_id, init_res["id"])


def assemble_and_publish():
    print("جاري تأليف حدوتة الفواكه عبر Gemini...", flush=True)
    story = generate_story()
    print(f"عنوان الحدوتة: {story['title']}", flush=True)

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"جاري تجهيز المشهد {idx + 1}...", flush=True)
        clip = create_scene_assets(idx, scene["narration"], scene["image_prompt"])
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final_video = "final_short.mp4"
    print("جاري دمج الفيديو النهائي بجودة عالية...", flush=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
        "-level", "4.0", "-crf", "18", "-c:a", "aac", "-ar", "44100",
        "-ac", "2", "-b:a", "128k", "-movflags", "+faststart", final_video
    ], check=True)

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
