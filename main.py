import os
import re
import json
import time
import shutil
import urllib.parse
import subprocess
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# تثبيت مكتبات رسم الترجمة العربية على الفيديو تلقائياً
subprocess.run([
    "pip", "install", "-q", "pillow", "arabic-reshaper", "python-bidi"
], check=False)

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_PATH = "Cairo-Bold.ttf"


def ensure_arabic_font():
    if os.path.exists(FONT_PATH) and os.path.getsize(FONT_PATH) > 10000:
        return FONT_PATH
    try:
        url = "https://github.com/google/fonts/raw/main/ofl/cairo/static/Cairo-Bold.ttf"
        r = requests.get(url, timeout=30)
        if r.ok:
            with open(FONT_PATH, "wb") as f:
                f.write(r.content)
            return FONT_PATH
    except Exception:
        pass
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def generate_story():
    prompt = """
    أنت كاتب سكريبتات شورتس وريلز محترف. اكتب حدوتة كوميدية سريعة وخفيفة الدم جداً باللهجة المصرية العامية الطبيعية (بدون أي تشكيل أو حركات إعراب نهائياً) تدور بين الفواكه المجسمة في المطبخ.

    قواعد صارمة لنجاح الفيديو:
    1. اكتب 6 مشاهد سريعة ومتتالية، كل مشهد من 10 إلى 14 كلمة فقط بالعامية المصرية السلسة (ممنوع الفصحى وممنوع التشكيل).
    2. وزع الحوار بين صوتين: "male" (للراوي أو الفاكهة الأولى مثل المانجا/الموز) و"female" (للفاكهة الثانية مثل الفراولة/التفاحة) ليكون حواراً تمثيلياً ممتعاً.
    3. ابدأ المشهد الأول بجملة صادمة أو مضحكة تخطف الانتباه فوراً.
    4. اجعل وصف الصورة (image_prompt) بالإنجليزية (أقل من 18 كلمة بدون فواصل أو رموز) يصف شكل الفاكهة الكرتونية وتعبيرات وجهها بدقة بأسلوب:
       "Cute 3D Pixar animation of an angry talking red strawberry character with big eyes in a bright kitchen"

    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان مصري قصير ومشوق للحدوتة",
      "scenes": [
        {
          "speaker": "male",
          "narration": "الجملة بالعامية المصرية بدون تشكيل",
          "image_prompt": "Cute 3D Pixar animation of a proud yellow mango character wearing sunglasses in a kitchen"
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
            print(f"تم تأليف السكريبت التمثيلي عبر: {model}", flush=True)
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    raise RuntimeError(f"فشل الاتصال بـ Gemini API: {res}")


def strip_diacritics(text):
    return re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)


def generate_audio(narration, speaker, audio_file):
    clean_text = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration).strip())
    primary_voice = "ar-EG-ShakirNeural" if speaker == "male" else "ar-EG-SalmaNeural"
    backup_voice = "ar-EG-SalmaNeural" if speaker == "male" else "ar-EG-ShakirNeural"

    for voice in [primary_voice, backup_voice]:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice, "--rate", "+10%",
                "--text", clean_text, "--write-media", audio_file
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(audio_file) and os.path.getsize(audio_file) > 500:
                print(f"تم تسجيل الصوت ({voice})", flush=True)
                return
        except Exception:
            time.sleep(2)

    raw_mp3 = f"raw_{audio_file}"
    encoded_text = urllib.parse.quote(clean_text)
    gtts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded_text}"
    r = requests.get(gtts_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    with open(raw_mp3, "wb") as f:
        f.write(r.content)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", raw_mp3,
        "-af", "atempo=1.2", audio_file
    ], check=True)


def download_scene_image(index, image_prompt, img_file):
    clean_desc = re.sub(r'[^a-zA-Z0-9 ]', ' ', image_prompt)
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:130]
    full_prompt = (
        f"Cute 3D Pixar Disney movie animation, {clean_desc}, "
        f"expressive face, cute hands, ultra detailed 3D render, vibrant studio lighting, vertical 9:16"
    )

    # 1. المحرك الأول: Hugging Face FLUX.1-schnell (جودة أصلية فائقة)
    if HF_TOKEN:
        for hf_url in [
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        ]:
            try:
                headers = {"Authorization": f"Bearer {HF_TOKEN}"}
                payload = {
                    "inputs": full_prompt,
                    "parameters": {"width": 768, "height": 1344, "num_inference_steps": 4}
                }
                res = requests.post(hf_url, headers=headers, json=payload, timeout=60)
                if res.status_code == 200 and len(res.content) > 8000:
                    with open(img_file, "wb") as f:
                        f.write(res.content)
                    print(f"تم تصميم صورة المشهد {index + 1} عبر محرك FLUX.1 الرسمي", flush=True)
                    return
            except Exception:
                pass

    # 2. المحرك الثاني: Pollinations Flux بدون علامة مائية
    if index > 0:
        time.sleep(8)

    encoded_prompt = urllib.parse.quote(full_prompt, safe='')
    base_seed = int(time.time()) + (index * 777)

    urls_to_try = [
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1344&model=flux&nologo=true&seed={base_seed + 1}",
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1344&model=turbo&nologo=true&seed={base_seed + 2}",
        f"https://pollinations.ai/p/{encoded_prompt}?width=768&height=1344&model=flux&nologo=true&seed={base_seed + 3}"
    ]

    for attempt, img_url in enumerate(urls_to_try):
        try:
            headers = {"User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/12{attempt}.0.0.0"}
            res = requests.get(img_url, headers=headers, timeout=75)
            if res.status_code == 200 and len(res.content) > 8000:
                with open(img_file, "wb") as f:
                    f.write(res.content)
                print(f"تم تصميم صورة المشهد {index + 1} بجودة 3D Pixar", flush=True)
                return
        except Exception:
            pass
        time.sleep(8)

    if index > 0 and os.path.exists(f"scene_{index - 1}.jpg"):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", f"scene_{index - 1}.jpg",
            "-vf", "hflip,eq=saturation=1.12", "-frames:v", "1", "-update", "1", img_file
        ], check=True)
        return

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0xFF8C00:s=1080x1920:d=1",
        "-frames:v", "1", "-update", "1", img_file
    ], check=True)


def render_subtitle_overlay(text, overlay_png):
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 52)

    clean_text = strip_diacritics(re.sub(r'["\'«»„“”*]', '', text).strip())
    words = clean_text.split()
    lines = []
    current = []
    for w in words:
        current.append(w)
        if len(current) >= 5:
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))

    reshaped_lines = [get_display(arabic_reshaper.reshape(line)) for line in lines[:3]]

    box_top = 1380
    line_height = 78
    total_h = len(reshaped_lines) * line_height + 50
    draw.rounded_rectangle(
        [(70, box_top), (1010, box_top + total_h)],
        radius=35,
        fill=(15, 15, 25, 195),
        outline=(255, 215, 0, 230),
        width=4
    )

    y_pos = box_top + 22
    for r_line in reshaped_lines:
        bbox = draw.textbbox((0, 0), r_line, font=font)
        w = bbox[2] - bbox[0]
        x_pos = (1080 - w) // 2
        draw.text((x_pos + 3, y_pos + 3), r_line, font=font, fill=(0, 0, 0, 255))
        draw.text((x_pos, y_pos), r_line, font=font, fill=(255, 245, 157, 255))
        y_pos += line_height

    img.save(overlay_png, "PNG")


def create_scene_assets(index, scene):
    narration = scene["narration"]
    speaker = scene.get("speaker", "female" if index % 2 else "male")
    image_prompt = scene["image_prompt"]

    audio_file = f"scene_{index}.mp3"
    generate_audio(narration, speaker, audio_file)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, img_file)

    overlay_png = f"sub_{index}.png"
    render_subtitle_overlay(narration, overlay_png)

    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    if index % 2 == 0:
        z_expr = "min(zoom+0.0022,1.28)"
    else:
        z_expr = "if(eq(on,1),1.28,max(zoom-0.0022,1.0))"

    filter_complex = (
        f"[0:v]scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
        f"eq=saturation=1.15:contrast=1.05,"
        f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps},setsar=1[bg];"
        f"[bg][1:v]overlay=0:0,format=yuv420p[v]"
    )

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", img_file,
        "-loop", "1", "-i", overlay_png,
        "-i", audio_file,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
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
            "description": f"{title} 🍓🍍\n\n#حواديت #قصص_الفواكه #حدوتة #reels",
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
                data={"reqtype": "fileupload", "time": "1h"},
                files={"fileToUpload": f},
                timeout=120
            )
        if r.ok and r.text.strip().startswith("https://"):
            return r.text.strip()
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
    # انتظار انتهاء معالجة الفيديو داخل سيرفرات إنستجرام
    for _ in range(40):
        status_res = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code", "access_token": META_ACCESS_TOKEN},
            timeout=30
        ).json()
        code = status_res.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"رفض إنستجرام معالجة الفيديو: {status_res}")
        time.sleep(6)

    # إعادة محاولة النشر تلقائياً إذا ظهر كود 9007 (Media is not ready)
    for attempt in range(8):
        pub_res = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
            timeout=60
        ).json()
        if "id" in pub_res:
            print(f"[Instagram Reels] تم النشر بنجاح: {pub_res['id']}", flush=True)
            return
        err_code = pub_res.get("error", {}).get("code")
        if err_code == 9007:
            print(f"[Instagram] جاري انتظار اكتمال المعالجة النهائية ({attempt + 1}/8)...", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError(f"فشل نشر إنستجرام: {pub_res}")

    raise RuntimeError("استغرق سيرفر إنستجرام وقتاً أطول من المعتاد لمعالجة الفيديو")


def upload_to_instagram_reels(video_path, title, ig_user_id):
    caption = f"{title} 🍓🥭\n\n#حواديت #قصص_الفواكه #حدوتة #reels"
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
    print("جاري تأليف حدوتة الفواكه التمثيلية عبر Gemini...", flush=True)
    story = generate_story()
    print(f"عنوان الحدوتة: {story['title']}", flush=True)

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"جاري تجهيز المشهد {idx + 1}...", flush=True)
        clip = create_scene_assets(idx, scene)
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري دمج المشاهد وإضافة الخلفية الصوتية...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    # إضافة نغمة خلفية هادئة جداً تحت الحوار لكسر الصمت وضبط معايير يوتيوب وإنستجرام
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "sine=frequency=432:sample_rate=44100",
        "-filter_complex",
        "[1:a]volume=0.015,lowpass=f=300[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", "-map", "[a]",
        "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
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
