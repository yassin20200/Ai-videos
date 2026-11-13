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

# تثبيت مكتبة الاتصال بكروت الشاشة المجانية على Hugging Face ومكتبات الترجمة
subprocess.run([
    "pip", "install", "-q", "gradio_client", "pillow", "arabic-reshaper", "python-bidi"
], check=False)

from gradio_client import Client, handle_file
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
FONT_PATH = "Cairo-Black.ttf"


def ensure_arabic_font():
    if os.path.exists(FONT_PATH) and os.path.getsize(FONT_PATH) > 10000:
        return FONT_PATH
    try:
        url = "https://github.com/google/fonts/raw/main/ofl/cairo/static/Cairo-Black.ttf"
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
    أنت صانع أفلام شورتس درامية وكوميدية على غرار قناة "Fruits AI" الشهيرة.
    اكتب قصة درامية قصيرة ومشوقة جداً (5 مشاهد سريعة) بالعامية المصرية السلسة (بدون أي تشكيل نهائياً) تدور حول شخصيات بشرية لها رؤوس فواكه (مثلاً: طفل برأس فراولة، أب غاضب برأس بطيخة أو فراولة، دكتور برأس موزة يرتدي بالطو أبيض ونظارة، طلاب برؤوس توت أو مانجو في المدرسة).

    قواعد صارمة:
    1. اكتب الحوار كتمثيل مباشر بين الشخصيات بالعامية المصرية الطبيعية بدون تشكيل، وكل مشهد من 8 إلى 12 كلمة فقط.
    2. حدد نوع المتحدث في كل مشهد: "male" (للأب أو الدكتور أو الولد) أو "female" (للأم أو البنت).
    3. اكتب وصف الصورة (image_prompt) بالإنجليزية ليصف شخصية بجسم بشري يرتدي ملابس عادية ورأس فاكهة كبير بتعبيرات وجه درامية واضحة مثل:
       "3D Pixar animation of a sad boy with a giant strawberry head wearing a striped hoodie crying at a dinner table while an angry father with a giant strawberry head in a plaid shirt yells"
    4. اكتب وصف الحركة (motion_prompt) بالإنجليزية لتحريك الفيديو مثل:
       "The strawberry character is talking expressively with mouth moving, gesturing with hands, blinking, cinematic 3d animation"

    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان درامي مشوق للحدوتة",
      "scenes": [
        {
          "speaker": "male",
          "narration": "الجملة التمثيلية بالعامية المصرية بدون تشكيل",
          "image_prompt": "3D Pixar animation of a character with a giant strawberry head wearing a hoodie...",
          "motion_prompt": "Character talking expressively, mouth moving, head nodding, smooth 3D animation"
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
            print(f"تم تأليف القصة عبر: {model}", flush=True)
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
                "edge-tts", "--voice", voice, "--rate", "+8%",
                "--text", clean_text, "--write-media", audio_file
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(audio_file) and os.path.getsize(audio_file) > 500:
                print(f"تم تسجيل التمثيل الصوتي ({voice})", flush=True)
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
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:150]
    full_prompt = (
        f"3D Pixar Disney animation style, anthropomorphic human body wearing clothes with a giant fruit head, "
        f"{clean_desc}, expressive eyes and mouth, dramatic cinematic lighting, vertical 9:16"
    )

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
                    print(f"تم تصميم صورة المشهد {index + 1} عبر FLUX.1", flush=True)
                    return
            except Exception:
                pass

    if index > 0:
        time.sleep(7)

    encoded_prompt = urllib.parse.quote(full_prompt, safe='')
    base_seed = int(time.time()) + (index * 777)

    for attempt, model in enumerate(["flux", "turbo", "flux"]):
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1344&model={model}&nologo=true&seed={base_seed + attempt}"
            res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=75)
            if res.status_code == 200 and len(res.content) > 8000:
                with open(img_file, "wb") as f:
                    f.write(res.content)
                print(f"تم تصميم صورة المشهد {index + 1} بجودة 3D", flush=True)
                return
        except Exception:
            pass
        time.sleep(7)

    if index > 0 and os.path.exists(f"scene_{index - 1}.jpg"):
        shutil.copyfile(f"scene_{index - 1}.jpg", img_file)
        return

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x222233:s=1080x1920:d=1",
        "-frames:v", "1", "-update", "1", img_file
    ], check=True)


def animate_image_with_ai(index, img_file, motion_prompt, out_raw_video):
    """تحويل الصورة الثابتة إلى فيديو متحرك حقيقي عبر Hugging Face Spaces GPU مجاناً"""
    spaces_to_try = [
        "Lightricks/LTX-Video",
        "Wan-AI/Wan2.1",
        "zai-org/CogVideoX-5B-Space"
    ]
    for space_id in spaces_to_try:
        try:
            print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({space_id})...", flush=True)
            client = Client(space_id, hf_token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            result = client.predict(
                prompt=f"{motion_prompt}, 3D Pixar animation, talking mouth movement, expressive character",
                image=handle_file(img_file),
                api_name="/image_to_video"
            )
            video_path = result[0] if isinstance(result, (list, tuple)) else result
            if isinstance(video_path, dict) and "video" in video_path:
                video_path = video_path["video"]
            if video_path and os.path.exists(str(video_path)):
                shutil.copyfile(str(video_path), out_raw_video)
                print(f"تم تحريك المشهد {index + 1} إلى فيديو فعلي بنجاح!", flush=True)
                return True
        except Exception as e:
            print(f"انتقال لمحرك التحريك التالي للمشهد {index + 1}: { str(e)[:80] }", flush=True)
    return False


def render_karaoke_chunk_png(words_chunk, highlight_idx, png_path):
    """رسم الترجمة بأسلوب Fruits AI (كلمات بيضاء والكلمة النشطة باللون الأصفر مع حدود سوداء سميكة)"""
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 64)

    y_pos = 1520
    reshaped_words = [get_display(arabic_reshaper.reshape(w)) for w in words_chunk]
    # في العربية نرتب الكلمات من اليمين لليسار
    widths = [draw.textbbox((0, 0), rw, font=font)[2] for rw in reshaped_words]
    space_w = 24
    total_w = sum(widths) + space_w * (len(reshaped_words) - 1)

    current_right = (1080 + total_w) // 2
    for idx, rw in enumerate(reshaped_words):
        w = widths[idx]
        x_pos = current_right - w
        color = (255, 225, 0, 255) if idx == highlight_idx else (255, 255, 255, 255)

        # حدود سوداء سميكة حول الكلمات كما في Flashloop
        for dx in (-4, -2, 0, 2, 4):
            for dy in (-4, -2, 0, 2, 4):
                if dx != 0 or dy != 0:
                    draw.text((x_pos + dx, y_pos + dy), rw, font=font, fill=(0, 0, 0, 255))
        draw.text((x_pos, y_pos), rw, font=font, fill=color)
        current_right = x_pos - space_w

    img.save(png_path, "PNG")


def create_scene_assets(index, scene):
    narration = scene["narration"]
    speaker = scene.get("speaker", "male")
    image_prompt = scene["image_prompt"]
    motion_prompt = scene.get("motion_prompt", "Character talking expressively, moving hands, 3D animation")

    audio_file = f"scene_{index}.mp3"
    generate_audio(narration, speaker, audio_file)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_motion_video = f"base_motion_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    # محاولة التحريك بالذكاء الاصطناعي أولاً، وإذا كانت السيرفرات المجانية مزدحمة يطبق تحريك ديناميكي متقدم
    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
            "-an", base_motion_video
        ], check=True)
    else:
        # تحريك ديناميكي يحاكي نبض الكاميرا وحركة التحدث مع الصوت
        z_expr = "1.08+0.04*sin(on/4)+0.0015*on"
        x_expr = "iw/2-(iw/zoom/2)+18*sin(on/6)"
        y_expr = "ih/2-(ih/zoom/2)+12*cos(on/5)"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.15:contrast=1.05,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={total_frames}:s=1080x1920:fps={fps},setsar=1"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_file,
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-an", base_motion_video
        ], check=True)

    # تقسيم النص إلى مجموعات من 3 كلمات وتلوين الكلمة المنطوقة بالأصفر بالتتابع
    clean_words = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration).strip()).split()
    if not clean_words:
        clean_words = ["..."]

    chunks = [clean_words[i:i + 3] for i in range(0, len(clean_words), 3)]
    steps = []
    for ch in chunks:
        for w_idx in range(len(ch)):
            steps.append((ch, w_idx))

    step_dur = duration / max(len(steps), 1)
    inputs_cmd = ["-i", base_motion_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"

    for s_idx, (ch_words, hi_idx) in enumerate(steps):
        png_file = f"sub_{index}_{s_idx}.png"
        render_karaoke_chunk_png(ch_words, hi_idx, png_file)
        inputs_cmd.extend(["-loop", "1", "-i", png_file])
        start_t = round(s_idx * step_dur, 2)
        end_t = round((s_idx + 1) * step_dur, 2)
        next_stream = f"[v{s_idx}]"
        inp_idx = s_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    filter_parts.append(f"{last_stream}format=yuv420p[vout]")
    filter_complex = ";".join(filter_parts)

    video_file = f"scene_{index}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",
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
            "title": f"{title[:80]} 🍓🍌 #shorts",
            "description": f"{title}\n\n#حواديت #قصص_الفواكه #انيميشن #fruits_ai #shorts",
            "tags": ["shorts", "حواديت", "قصص الفواكه", "انيميشن", "fruits ai"],
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
            "description": f"{title} 🍓🍌\n\n#حواديت #قصص_الفواكه #انيميشن #reels",
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

    for attempt in range(8):
        pub_res = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
            timeout=60
        ).json()
        if "id" in pub_res:
            print(f"[Instagram Reels] تم النشر بنجاح: {pub_res['id']}", flush=True)
            return
        if pub_res.get("error", {}).get("code") == 9007:
            print(f"[Instagram] انتظار جاهزية النشر النهائي ({attempt + 1}/8)...", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError(f"فشل نشر إنستجرام: {pub_res}")


def upload_to_instagram_reels(video_path, title, ig_user_id):
    caption = f"{title} 🍓🍌\n\n#حواديت #قصص_الفواكه #انيميشن #reels"
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
    print("جاري تأليف دراما الفواكه بأسلوب Fruits AI...", flush=True)
    story = generate_story()
    print(f"عنوان القصة: {story['title']}", flush=True)

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"جاري تجهيز وتحريك المشهد {idx + 1}...", flush=True)
        clip = create_scene_assets(idx, scene)
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final_video = "final_short.mp4"
    print("جاري دمج الفيديو النهائي...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt",
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
