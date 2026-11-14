import os
import re
import json
import time
import base64
import shutil
import urllib.parse
import subprocess
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from gradio_client import Client, handle_file
from PIL import Image, ImageDraw, ImageFont, features
import arabic_reshaper
from bidi.algorithm import get_display

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_PATH = "Cairo-Black.ttf"

if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN

# مكتبة مؤثرات صوتية حقيقية من استوديو Google الرسمي (مجانية وسريعة ومباشرة)
GOOGLE_STUDIO_SFX = {
    "pop": "https://actions.google.com/sounds/v1/cartoon/pop.ogg",
    "boing": "https://actions.google.com/sounds/v1/cartoon/cartoon_boing.ogg",
    "whoosh": "https://actions.google.com/sounds/v1/foley/whoosh.ogg",
    "shock": "https://actions.google.com/sounds/v1/cartoon/concussive_hit_guitar_boing.ogg",
    "magic": "https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg",
    "funny_slip": "https://actions.google.com/sounds/v1/cartoon/slide_whistle_to_drum.ogg",
    "steps": "https://actions.google.com/sounds/v1/foley/footsteps_on_wood.ogg",
    "cheer": "https://actions.google.com/sounds/v1/crowds/battle_crowd_celebrate_stutter.ogg"
}


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
    أنت مخرج أفلام أنيميشن قصيرة عالمي متخصص في صناعة فيديوهات Reels وShorts المليونية بأسلوب 3D Pixar Disney السينمائي المذهل.
    ابتكر فكرة فيديو قصير عبقرية وخاطفة للأنظار (5 مشاهد متتالية) تعتمد على الكوميديا البصرية الذكية، المفاجآت غير المتوقعة، أو المواقف المؤثرة لشخصيات كرتونية ثلاثية الأبعاد محبوبة (مثل: روبوت صغير لطيف يحاول طهي كعكة، قطط أو كائنات لطيفة في مهمة سرية داخل متجر، مخترع صغير يختبر جهازاً سحرياً ينقلب عليه بطريقة مضحكة).

    قواعد الإخراج الاحترافي:
    1. حافظ على ثبات شكل الشخصية الرئيسية في كل المشاهد عبر كتابة وصف ثابت لها بالإنجليزية في حقل `character_sheet`، وكرر هذا الوصف داخل `image_prompt` لكل مشهد.
    2. الفيديو يعتمد بشكل أساسي على الحركة البصرية والمؤثرات الصوتية (SFX):
       - في المشاهد التي تعتمد على الحركة والمفاجأة البصرية فقط، يمكنك جعل `narration` تعبيراً صوتياً قصيراً جداً أو جملة خاطفة (من 2 إلى 6 كلمات فقط بالعامية المصرية بدون أي تشكيل، أو اتركها فارغة "" إذا كان المشهد صامتاً يعتمد على المؤثرات الصوتية فقط!).
       - في المشاهد الحوارية، اجعل الجملة طبيعية جداً وسريعة ومشوقة (بحد أقصى 7 كلمات بدون تشكيل).
    3. اختر المؤثر الصوتي الرئيسي (sfx_type) لكل مشهد من هذه القائمة:
       ["pop", "boing", "whoosh", "shock", "magic", "funny_slip", "steps", "cheer"]
    4. اكتب وصف الصورة (image_prompt) بالإنجليزية بدقة سينمائية عالية يصف الشخصية والملابس الأنيقة الكاملة والإضاءة والبيئة بأسلوب Pixar.
    5. اكتب وصف الحركة (motion_prompt) بالإنجليزية لتحريك المشهد بالذكاء الاصطناعي (حركة الكاميرا + حركة الشخصية الواضحة).

    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان قصير ومشوق جداً للفيديو",
      "character_sheet": "A cute chubby 3D Pixar little robot with glowing blue eyes and an orange scarf",
      "scenes": [
        {
          "speaker": "male",
          "sfx_type": "boing",
          "narration": "إيه الزرار الغريب ده؟",
          "image_prompt": "Masterpiece 3D Pixar Disney animation, A cute chubby 3D Pixar little robot with glowing blue eyes and an orange scarf standing in a futuristic kitchen looking at a giant red button, cinematic lighting, 8k, vertical 9:16",
          "motion_prompt": "3D Pixar animation, the cute robot tilts its head curiously and reaches out its hand to press the glowing button, smooth camera zoom"
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
            print(f"تم تأليف السيناريو السينمائي عبر: {model}", flush=True)
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    raise RuntimeError(f"فشل الاتصال بـ Gemini API: {res}")


def strip_diacritics(text):
    return re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)


def create_sfx_audio(sfx_type, sfx_file):
    """تحميل مؤثر صوتي استوديو حقيقي أو توليده بجودة عالية"""
    raw_ogg = f"raw_{sfx_file}.ogg"
    sfx_url = GOOGLE_STUDIO_SFX.get(sfx_type, GOOGLE_STUDIO_SFX["pop"])

    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(raw_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", raw_ogg,
                "-af", "atrim=0:1.6,afade=t=out:st=1.2:d=0.4,volume=0.55",
                "-ar", "44100", "-ac", "2", sfx_file
            ], check=True)
            return
    except Exception:
        pass

    # بديل مركب متعدد الطبقات في حال عدم توفر الإنترنت للملف الصوتي
    synth_filters = {
        "pop": "sine=f=480:d=0.15,vibrato=f=15:d=0.8,afade=t=out:st=0.03:d=0.12,volume=0.45",
        "boing": "sine=f=280:d=0.45,vibrato=f=22:d=0.9,afade=t=out:st=0.1:d=0.35,volume=0.45",
        "whoosh": "anoisesrc=d=0.4:c=pink,bandpass=f=800:width_type=h:w=500,afade=t=in:d=0.12,afade=t=out:st=0.18:d=0.22,volume=0.5",
        "shock": "sine=f=160:d=0.5,vibrato=f=14:d=0.85,afade=t=out:st=0.15:d=0.35,volume=0.45",
        "magic": "sine=f=920:d=0.5,tremolo=f=18:d=0.9,afade=t=out:st=0.15:d=0.35,volume=0.35",
        "funny_slip": "sine=f=620:d=0.4,vibrato=f=25:d=0.9,afade=t=out:st=0.1:d=0.3,volume=0.45",
        "steps": "anoisesrc=d=0.25:c=brown,lowpass=f=400,afade=t=out:st=0.05:d=0.2,volume=0.5",
        "cheer": "sine=f=540:d=0.45,tremolo=f=12:d=0.8,afade=t=out:st=0.15:d=0.3,volume=0.4"
    }
    chosen = synth_filters.get(sfx_type, synth_filters["pop"])
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", chosen,
        "-ar", "44100", "-ac", "2", sfx_file
    ], check=True)


def generate_audio_with_sfx(narration, speaker, sfx_type, final_audio_file):
    clean_text = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration or "").strip())
    voice_file = f"voice_{final_audio_file}"
    sfx_file = f"sfx_{final_audio_file}"

    create_sfx_audio(sfx_type, sfx_file)

    # إذا كان المشهد بصرياً صامتاً (بدون حوار كلامي)، نصنع شريطاً صوتياً غنياً بالمؤثرات الصوتية السينمائية لمدة 3.8 ثانية
    if not clean_text:
        second_sfx = f"sfx2_{final_audio_file}"
        create_sfx_audio("whoosh" if sfx_type != "whoosh" else "boing", second_sfx)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=3.8",
            "-i", sfx_file, "-i", second_sfx,
            "-filter_complex",
            "[1:a]adelay=150|150[s1];[2:a]adelay=1800|1800[s2];[0:a][s1][s2]amix=inputs=3:duration=first:dropout_transition=0[a]",
            "-map", "[a]", "-ar", "44100", "-ac", "2", final_audio_file
        ], check=True)
        print("تم تصميم هندسة صوتية تفاعلية (SFX Only) للمشهد البصري", flush=True)
        return

    primary_voice = "ar-EG-ShakirNeural" if speaker == "male" else "ar-EG-SalmaNeural"
    backup_voice = "ar-EG-SalmaNeural" if speaker == "male" else "ar-EG-ShakirNeural"

    voice_ok = False
    for voice in [primary_voice, backup_voice, "ar-SA-HamedNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice, "--rate", "+8%",
                "--text", clean_text, "--write-media", voice_file
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(voice_file) and os.path.getsize(voice_file) > 500:
                print(f"تم تسجيل التمثيل الصوتي ({voice})", flush=True)
                voice_ok = True
                break
        except Exception:
            time.sleep(2)

    if not voice_ok:
        encoded_text = urllib.parse.quote(clean_text)
        gtts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded_text}"
        r = requests.get(gtts_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        with open(voice_file, "wb") as f:
            f.write(r.content)

    # دمج المؤثر الصوتي (SFX) مع التمثيل الصوتي وإضافة هامش زمني بصري (0.8 ثانية) للاستمتاع بالمشهد
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", sfx_file, "-i", voice_file,
        "-filter_complex",
        "[1:a]adelay=320|320,apad=pad_dur=0.8[v];[0:a][v]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map", "[a]", "-ar", "44100", "-ac", "2", final_audio_file
    ], check=True)


def download_scene_image(index, image_prompt, character_sheet, img_file):
    clean_desc = re.sub(r'[^a-zA-Z0-9 ,.-]', ' ', image_prompt)
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:200]
    clean_char = re.sub(r'[^a-zA-Z0-9 ,.-]', ' ', character_sheet or "").strip()[:100]

    full_prompt = (
        f"Masterpiece 3D Pixar Disney animation movie still, {clean_char}, {clean_desc}, "
        f"cute expressive character wearing modest colorful outfit, big detailed eyes, "
        f"Pixar studio volumetric lighting, vibrant colors, ultra detailed 3D octane render, vertical 9:16"
    )

    # الأداة 1: توليد الصور عبر Google Gemini Imagen / Flash Image Generation مباشرة
    if GEMINI_API_KEY:
        try:
            imagen_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
            imagen_payload = {
                "instances": [{"prompt": full_prompt}],
                "parameters": {"sampleCount": 1, "aspectRatio": "9:16"}
            }
            r = requests.post(imagen_url, json=imagen_payload, timeout=45)
            if r.status_code == 200:
                preds = r.json().get("predictions", [])
                if preds and "bytesBase64Encoded" in preds[0]:
                    with open(img_file, "wb") as f:
                        f.write(base64.b64decode(preds[0]["bytesBase64Encoded"]))
                    print(f"تم تصميم صورة المشهد {index + 1} عبر Google Imagen 3!", flush=True)
                    return
        except Exception:
            pass

    # الأداة 2: التوليد عبر Hugging Face Inference API (FLUX.1-schnell)
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
                res = requests.post(hf_url, headers=headers, json=payload, timeout=75)
                if res.status_code == 200 and len(res.content) > 10000:
                    with open(img_file, "wb") as f:
                        f.write(res.content)
                    print(f"تم تصميم صورة المشهد {index + 1} عبر محرك FLUX.1 الرسمي!", flush=True)
                    return
            except Exception as e:
                print(f"تنبيه HF Image API: {e}", flush=True)

    # الأداة 3: التوليد عبر مساحات Gradio للصور (FLUX.1-schnell Space)
    for img_space in ["black-forest-labs/FLUX.1-schnell", "ByteDance/SDXL-Lightning"]:
        try:
            try:
                c = Client(img_space, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            except TypeError:
                c = Client(img_space, verbose=False)
            res = c.predict(
                prompt=full_prompt,
                seed=0,
                randomize_seed=True,
                width=768,
                height=1344,
                num_inference_steps=4,
                api_name="/infer"
            )
            img_path = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(img_path, dict) and "path" in img_path:
                img_path = img_path["path"]
            if isinstance(img_path, str) and os.path.exists(img_path):
                shutil.copyfile(img_path, img_file)
                print(f"تم تصميم صورة المشهد {index + 1} عبر مساحة ({img_space})!", flush=True)
                return
        except Exception:
            pass

    # الأداة 4: البديل الاحتياطي عبر Pollinations Flux
    if index > 0:
        time.sleep(5)

    encoded_prompt = urllib.parse.quote(full_prompt, safe='')
    base_seed = int(time.time()) + (index * 777)

    for attempt, model in enumerate(["flux", "turbo"]):
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=768&height=1344&model={model}&nologo=true&seed={base_seed + attempt}"
            res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=75)
            if res.status_code == 200 and len(res.content) > 10000:
                with open(img_file, "wb") as f:
                    f.write(res.content)
                print(f"تم تصميم صورة المشهد {index + 1} بجودة 3D Pixar", flush=True)
                return
        except Exception:
            pass
        time.sleep(5)

    if index > 0 and os.path.exists(f"scene_{index - 1}.jpg"):
        shutil.copyfile(f"scene_{index - 1}.jpg", img_file)
        return

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x1A1A2E:s=1080x1920:d=1",
        "-frames:v", "1", "-update", "1", img_file
    ], check=True)


def extract_video_path(result):
    if isinstance(result, str) and os.path.exists(result):
        return result
    if isinstance(result, dict):
        for k in ("video", "path", "url"):
            if k in result and result[k] and os.path.exists(str(result[k])):
                return str(result[k])
    if isinstance(result, (list, tuple)):
        for item in result:
            found = extract_video_path(item)
            if found:
                return found
    return None


def animate_image_with_ai(index, img_file, motion_prompt, out_raw_video):
    """تحريك الصورة فعلياً عبر 6 محركات ذكاء اصطناعي (Image-to-Video) مع استكشاف تلقائي للواجهة"""
    spaces_to_try = [
        ("Wan-AI/Wan2.1", "/image_to_video"),
        ("multimodalart/wan-2-1-fast", "/predict"),
        ("Lightricks/LTX-Video", "/image_to_video"),
        ("zai-org/CogVideoX-5B-Space", "/predict"),
        ("THUDM/CogVideoX-5B", "/predict"),
        ("ali-vilab/i2vgen-xl", "/predict")
    ]
    full_motion = f"{motion_prompt}, 3D Pixar animation, smooth expressive character movement, high quality"

    for space_id, default_api in spaces_to_try:
        try:
            print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({space_id})...", flush=True)
            try:
                client = Client(space_id, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            except TypeError:
                client = Client(space_id, verbose=False)

            result = None
            try:
                api_info = client.view_api(return_format="dict")
                named_endpoints = list(api_info.get("named_endpoints", {}).keys())
                target_api = default_api if default_api in named_endpoints else (named_endpoints[0] if named_endpoints else default_api)
                result = client.predict(
                    prompt=full_motion,
                    image=handle_file(img_file),
                    api_name=target_api
                )
            except Exception:
                try:
                    result = client.predict(
                        handle_file(img_file),
                        full_motion,
                        fn_index=0
                    )
                except Exception:
                    result = client.predict(
                        full_motion,
                        handle_file(img_file),
                        fn_index=0
                    )

            v_path = extract_video_path(result)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {space_id}!", flush=True)
                return True
        except Exception as e:
            print(f"انتقال لمحرك التحريك التالي للمشهد {index + 1}: {str(e)[:90]}", flush=True)
    return False


def render_subtitle_phrase_png(phrase_text, png_path):
    """رسم الترجمة العربية بوضوح تام واتجاه سليم 100% في منتصف أسفل الشاشة"""
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 58)

    has_raqm = features.check("raqm")
    if has_raqm:
        display_text = phrase_text
        text_kwargs = {"direction": "rtl", "language": "ar"}
    else:
        display_text = get_display(arabic_reshaper.reshape(phrase_text))
        text_kwargs = {}

    try:
        bbox = draw.textbbox((0, 0), display_text, font=font, **text_kwargs)
    except Exception:
        text_kwargs = {}
        display_text = get_display(arabic_reshaper.reshape(phrase_text)) if not has_raqm else phrase_text
        bbox = draw.textbbox((0, 0), display_text, font=font)

    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    x_pos = (1080 - w) // 2
    y_pos = 1480

    pad_x, pad_y = 36, 22
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 12)],
        radius=28,
        fill=(10, 10, 18, 205),
        outline=(255, 215, 0, 240),
        width=4
    )

    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255), **text_kwargs)

    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 235, 59, 255), **text_kwargs)
    img.save(png_path, "PNG")


def create_scene_assets(index, scene, character_sheet):
    narration = scene.get("narration", "")
    speaker = scene.get("speaker", "male")
    sfx_type = scene.get("sfx_type", "pop")
    image_prompt = scene["image_prompt"]
    motion_prompt = scene.get("motion_prompt", "3D Pixar animation, smooth expressive movement")

    audio_file = f"scene_{index}.mp3"
    generate_audio_with_sfx(narration, speaker, sfx_type, audio_file)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = max(float(probe.stdout.strip()), 3.2)

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, character_sheet, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_motion_video = f"base_motion_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "fast",
            "-an", base_motion_video
        ], check=True)
    else:
        z_expr = "min(zoom+0.0020,1.24)" if index % 2 == 0 else "if(eq(on,1),1.24,max(zoom-0.0020,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.15:contrast=1.06,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},setsar=1"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_file,
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-an", base_motion_video
        ], check=True)

    clean_words = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration or "").strip()).split()
    video_file = f"scene_{index}.mp4"

    # إذا كان المشهد بصرياً بدون حوار، ندمج الفيديو مع المؤثرات الصوتية مباشرة بدون تشويه الشاشة بصندوق ترجمة فارغ
    if not clean_words:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", base_motion_video, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-t", str(duration), "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", video_file
        ], check=True)
        return video_file

    phrases = [" ".join(clean_words[i:i + 4]) for i in range(0, len(clean_words), 4)]
    step_dur = duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_motion_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"

    for p_idx, phrase in enumerate(phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_subtitle_phrase_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-i", png_file])
        start_t = round(p_idx * step_dur, 2)
        end_t = round((p_idx + 1) * step_dur, 2)
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    filter_parts.append(f"{last_stream}format=yuv420p[vout]")
    filter_complex = ";".join(filter_parts)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
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
            "title": f"{title[:80]} ✨🎬 #shorts",
            "description": f"{title}\n\n#انيميشن #قصص #حكايات #3d_animation #shorts",
            "tags": ["shorts", "انيميشن", "قصص", "3d", "pixar"],
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
            "description": f"{title} ✨🎬\n\n#انيميشن #قصص #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def get_public_video_url(video_path):
    # 1. Catbox Litterbox (رابط مباشر سريع جداً لإنستجرام)
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

    # 2. Uguu.se Direct Link
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

    # 3. Tmpfiles Direct Link
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
    caption = f"{title} ✨🎬\n\n#انيميشن #قصص #حكايات #reels"
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
    print("جاري تأليف القصة السينمائية عبر Gemini...", flush=True)
    story = generate_story()
    print(f"عنوان القصة: {story['title']}", flush=True)
    character_sheet = story.get("character_sheet", "cute 3D Pixar animated character")

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"جاري تجهيز وتحريك المشهد {idx + 1}...", flush=True)
        clip = create_scene_assets(idx, scene, character_sheet)
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري دمج المشاهد وإضافة الموسيقى التصويرية السينمائية...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    # توليد خلفية موسيقية سينمائية دافئة متعددة التناغمات (Multi-Harmonic Ambient Chord) بدلاً من الطنين المفرد
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
        "-f", "lavfi", "-i", "sine=frequency=329.63:sample_rate=44100",
        "-filter_complex",
        "[1:a][2:a]amix=inputs=2,tremolo=f=1.5:d=0.45,lowpass=f=320,volume=0.025[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
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
