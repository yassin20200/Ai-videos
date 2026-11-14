import os
import re
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
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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

# مكتبة مؤثرات صوتية حقيقية من استوديو Google الرسمي
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

# مقطوعات موسيقية سينمائية وكوميدية حقيقية (Kevin MacLeod - Royalty Free) الخاصة بفيديوهات الشورتس والريلز العالمية
ROYALTY_FREE_BGM_URLS = [
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3",
    "https://upload.wikimedia.org/wikipedia/commons/transcoded/6/6f/Kevin_MacLeod_~_Sneaky_Snitch.ogg/Kevin_MacLeod_~_Sneaky_Snitch.ogg.mp3"
]


class PinnedSpace:
    """اتصال HTTP/2 موحد لمنع ضياع ملفات الفيديو بين السيرفرات المتعددة في مساحات Wan 2.2 و SVD"""
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
            raise RuntimeError(f"لم يتم العثور على رابط الفيديو في النتيجة: {output_data}")
        content = self.http.get(file_url).content
        if len(content) < 10000:
            raise RuntimeError("ملف الفيديو المحمل صغير جداً أو تالف")
        Path(dst).write_bytes(content)


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
    ابتكر قصة بصرية مشوقة جداً، ذكية، وممتعة (5 مشاهد متتالية) لشخصيات كرتونية ثلاثية الأبعاد محبوبة (مثل: قط صغير ذكي يرتدي وشاحاً في مغامرة داخل مطبخ عملاق، أو روبوت صغير لطيف يحاول إصلاح لعبة سحرية، أو سنجاب عبقري يخطط لسرقة بندقة عملاقة).

    قواعد الإخراج الصارمة:
    1. اكتب وصفاً ثابتاً ودقيقاً للشخصية الرئيسية بالإنجليزية في حقل `character_sheet` لضمان ثبات شكلها في كل المشاهد.
    2. في كل مشهد، اكتب جملة تفاعلية قصيرة جداً ومعبرة بالعامية المصرية بدون تشكيل (من 3 إلى 6 كلمات فقط)، ويمكنك ترك مشهد واحد فارغاً "" ليعتمد على المؤثرات الصوتية والحركة البصرية المفاجئة.
    3. اختر المؤثر الصوتي (sfx_type) لكل مشهد من القائمة:
       ["pop", "boing", "whoosh", "shock", "magic", "funny_slip", "steps", "cheer"]
    4. اكتب `image_prompt` بالإنجليزية يصف المشهد بتفاصيل سينمائية فائقة (Pixar 3D render, expressive eyes, rich textures, dramatic lighting) دون تكرار الجمل.
    5. اكتب `motion_prompt` بالإنجليزية يصف حركة الشخصية وحركة الكاميرا بوضوح شديد لتحريك الصورة بالذكاء الاصطناعي.

    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان قصير ومشوق جداً للفيديو",
      "character_sheet": "a cute fluffy ginger tabby kitten with big emerald eyes wearing a tiny blue knitted scarf",
      "scenes": [
        {
          "speaker": "male",
          "sfx_type": "boing",
          "narration": "إيه السمكة العملاقة دي؟",
          "image_prompt": "a cute fluffy ginger tabby kitten with big emerald eyes wearing a tiny blue knitted scarf standing on a wooden kitchen counter looking amazed at a glowing golden fishbowl, warm Pixar kitchen lighting",
          "motion_prompt": "The cute kitten tilts its head in awe, whiskers twitching, and steps forward curiously on the wooden counter, smooth camera push in"
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
    """تحميل مؤثر صوتي استوديو حقيقي من Google Studio Library"""
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
                "-af", "atrim=0:1.8,afade=t=out:st=1.3:d=0.5,volume=0.65",
                "-ar", "44100", "-ac", "2", sfx_file
            ], check=True)
            return
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=f=480:d=0.2,vibrato=f=15:d=0.8,afade=t=out:st=0.05:d=0.15,volume=0.45",
        "-ar", "44100", "-ac", "2", sfx_file
    ], check=True)


def generate_audio_with_sfx(narration, speaker, sfx_type, final_audio_file):
    clean_text = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration or "").strip())
    voice_file = f"voice_{final_audio_file}"
    sfx_file = f"sfx_{final_audio_file}"

    create_sfx_audio(sfx_type, sfx_file)

    if not clean_text:
        second_sfx = f"sfx2_{final_audio_file}"
        third_sfx = f"sfx3_{final_audio_file}"
        create_sfx_audio("funny_slip" if sfx_type != "funny_slip" else "boing", second_sfx)
        create_sfx_audio("pop", third_sfx)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=3.6",
            "-i", sfx_file, "-i", second_sfx, "-i", third_sfx,
            "-filter_complex",
            "[1:a]adelay=100|100[s1];[2:a]adelay=1300|1300[s2];[3:a]adelay=2500|2500[s3];"
            "[0:a][s1][s2][s3]amix=inputs=4:duration=first:dropout_transition=0[a]",
            "-map", "[a]", "-ar", "44100", "-ac", "2", final_audio_file
        ], check=True)
        print("تم تصميم هندسة صوتية تفاعلية متعددة الطبقات (SFX Action) للمشهد", flush=True)
        return

    primary_voice = "ar-EG-SalmaNeural" if speaker == "female" else "ar-EG-ShakirNeural"
    backup_voice = "ar-EG-ShakirNeural" if speaker == "female" else "ar-EG-SalmaNeural"

    voice_ok = False
    for voice in [primary_voice, backup_voice, "ar-SA-HamedNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice, "--rate", "+10%",
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

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", sfx_file, "-i", voice_file,
        "-filter_complex",
        "[1:a]adelay=250|250,apad=pad_dur=0.9[v];[0:a][v]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map", "[a]", "-ar", "44100", "-ac", "2", final_audio_file
    ], check=True)


def save_and_enhance_image(src_path_or_bytes, dst_file, is_bytes=False):
    """حفظ الصورة بدقة عالية جداً 1080x1920 مع تحسين الحدة والألوان السينمائية"""
    if is_bytes:
        with open("temp_raw_img", "wb") as f:
            f.write(src_path_or_bytes)
        img = Image.open("temp_raw_img").convert("RGB")
    else:
        img = Image.open(src_path_or_bytes).convert("RGB")

    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def download_scene_image(index, image_prompt, character_sheet, img_file):
    clean_desc = re.sub(r'[^a-zA-Z0-9 ,.-]', ' ', image_prompt)
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:220]
    clean_char = re.sub(r'[^a-zA-Z0-9 ,.-]', ' ', character_sheet or "").strip()[:120]

    # منع تكرار وصف الشخصية إذا كان موجوداً بالفعل داخل وصف المشهد
    if clean_char.lower()[:30] in clean_desc.lower():
        core_prompt = clean_desc
    else:
        core_prompt = f"{clean_char}, {clean_desc}"

    full_prompt = (
        f"3D Pixar Disney animation movie still, {core_prompt}, "
        f"expressive face, big detailed eyes, subsurface scattering, Pixar studio volumetric lighting, "
        f"rich vibrant colors, ultra detailed 8k octane render, vertical 9:16 aspect ratio"
    )

    # 1. التوليد عبر Hugging Face Router الرسمي (FLUX.1-schnell)
    if HF_TOKEN:
        try:
            hf_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            headers = {"Authorization": f"Bearer {HF_TOKEN}"}
            payload = {
                "inputs": full_prompt,
                "parameters": {"width": 1024, "height": 1792, "num_inference_steps": 4}
            }
            res = requests.post(hf_url, headers=headers, json=payload, timeout=75)
            if res.status_code == 200 and len(res.content) > 10000:
                save_and_enhance_image(res.content, img_file, is_bytes=True)
                print(f"تم تصميم صورة المشهد {index + 1} عبر HF Router FLUX.1 بدقة فائقة!", flush=True)
                return
        except Exception:
            pass

    # 2. التوليد عبر مساحات FLUX.1-dev و FLUX.1-schnell بدقة عالية 1024x1792
    for img_space, steps in [("black-forest-labs/FLUX.1-dev", 24), ("black-forest-labs/FLUX.1-schnell", 4)]:
        try:
            client = Client(img_space, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            if "dev" in img_space:
                res = client.predict(
                    prompt=full_prompt,
                    seed=0,
                    randomize_seed=True,
                    width=1024,
                    height=1792,
                    guidance_scale=3.5,
                    num_inference_steps=steps,
                    api_name="/infer"
                )
            else:
                res = client.predict(
                    prompt=full_prompt,
                    seed=0,
                    randomize_seed=True,
                    width=1024,
                    height=1792,
                    num_inference_steps=steps,
                    api_name="/infer"
                )
            img_path = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(img_path, dict) and "path" in img_path:
                img_path = img_path["path"]
            if isinstance(img_path, str) and os.path.exists(img_path):
                save_and_enhance_image(img_path, img_file, is_bytes=False)
                print(f"تم تصميم صورة المشهد {index + 1} عبر ({img_space}) بدقة فائقة!", flush=True)
                return
        except Exception as e:
            print(f"انتقال لمحرك الصور التالي بعد ({img_space}): {str(e)[:80]}", flush=True)

    # 3. البديل الاحتياطي عبر Pollinations Flux
    encoded_prompt = urllib.parse.quote(full_prompt, safe='')
    base_seed = int(time.time()) + (index * 777)
    for attempt, model in enumerate(["flux", "turbo"]):
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1792&model={model}&nologo=true&seed={base_seed + attempt}"
            res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=75)
            if res.status_code == 200 and len(res.content) > 10000:
                save_and_enhance_image(res.content, img_file, is_bytes=True)
                print(f"تم تصميم صورة المشهد {index + 1} عبر Pollinations Flux!", flush=True)
                return
        except Exception:
            pass
        time.sleep(4)

    if index > 0 and os.path.exists(f"scene_{index - 1}.jpg"):
        shutil.copyfile(f"scene_{index - 1}.jpg", img_file)
        return

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x1A1A2E:s=1080x1920:d=1",
        "-frames:v", "1", "-update", "1", img_file
    ], check=True)


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


def animate_image_with_ai(index, img_file, motion_prompt, out_raw_video):
    """
    تحريك الصورة فعلياً باستخدام المعاملات الدقيقة الموثقة لكل مساحة على Hugging Face:
    1. Wan 2.2 14B Fast (عبر PinnedSpace لمنع خطأ تعدد السيرفرات + Gradio Client)
    2. CogVideoX-5B-Space & THUDM/CogVideoX-5B (بالمعاملات الدقيقة من السجل: image_input, video_input=None, api_name='/generate')
    3. Lightricks/ltx-video-distilled (بالمعاملات الدقيقة: input_image_filepath, api_name='/image_to_video')
    4. AnimateLCM-SVD (بالمعاملات الدقيقة لاستهلاك كوتة منخفضة 60s فقط)
    """
    full_motion = f"{motion_prompt}, 3D Pixar animation, smooth expressive movement, lively action, high frame rate"
    neg_prompt = "low quality, worst quality, static, frozen, blurry, deformed, ugly, text, watermark"

    # --- المحرك 1: Wan 2.2 14B Fast عبر PinnedSpace HTTP/2 ---
    for wan_space in ["zerogpu-aoti/wan2-2-fp8da-aoti-faster", "r3gm/wan2-2-fp8da-aoti-preview2"]:
        try:
            print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({wan_space})...", flush=True)
            client = Client(wan_space, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=6,
                negative_prompt=neg_prompt,
                duration_seconds=3.5,
                guidance_scale=1.0,
                guidance_scale_2=1.0,
                seed=42 + index,
                randomize_seed=True,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {wan_space}!", flush=True)
                return True
        except Exception as e:
            print(f"تنبيه {wan_space} (Gradio): {str(e)[:90]}", flush=True)
            try:
                ps = PinnedSpace(wan_space, token=HF_TOKEN if HF_TOKEN else None)
                up_img = ps.upload(img_file)
                out = ps.call("/generate_video", [up_img, full_motion, 6, neg_prompt, 3.5, 1.0, 1.0, 42 + index, True])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {wan_space} (Pinned)!", flush=True)
                return True
            except Exception as e2:
                print(f"انتقال للمحرك التالي بعد {wan_space}: {str(e2)[:90]}", flush=True)

    # --- المحرك 2: CogVideoX-5B (المتصل في السجل بمعاملاته الدقيقة 100%) ---
    for cog_space in ["zai-org/CogVideoX-5B-Space", "THUDM/CogVideoX-5B"]:
        try:
            print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({cog_space})...", flush=True)
            client = Client(cog_space, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
            res = client.predict(
                prompt=full_motion,
                image_input=handle_file(img_file),
                video_input=None,
                video_strength=0.8,
                seed_value=-1,
                scale_status=True,
                rife_status=True,
                api_name="/generate"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {cog_space}!", flush=True)
                return True
        except Exception as e:
            print(f"انتقال للمحرك التالي بعد {cog_space}: {str(e)[:90]}", flush=True)

    # --- المحرك 3: Lightricks/ltx-video-distilled ---
    try:
        ltx_space = "Lightricks/ltx-video-distilled"
        print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({ltx_space})...", flush=True)
        client = Client(ltx_space, token=HF_TOKEN if HF_TOKEN else None, verbose=False)
        res = client.predict(
            prompt=full_motion,
            negative_prompt=neg_prompt,
            input_image_filepath=handle_file(img_file),
            input_video_filepath=None,
            height_ui=704,
            width_ui=512,
            mode="image-to-video",
            duration_ui=3.5,
            ui_frames_to_use=9,
            seed_ui=42 + index,
            randomize_seed=True,
            ui_guidance_scale=3.0,
            improve_texture_flag=True,
            api_name="/image_to_video"
        )
        v_path = extract_video_path(res)
        if v_path:
            shutil.copyfile(v_path, out_raw_video)
            print(f"🎉 تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {ltx_space}!", flush=True)
            return True
    except Exception as e:
        print(f"انتقال للمحرك التالي بعد LTX-Video: {str(e)[:90]}", flush=True)

    # --- المحرك 4: AnimateLCM-SVD (سريع جداً ويستهلك كوتة منخفضة) ---
    for svd_space in ["wangfuyun/AnimateLCM-SVD", "multimodalart/AnimateLCM-SVD-zerogpu"]:
        try:
            print(f"جاري تحريك المشهد {index + 1} بالذكاء الاصطناعي عبر ({svd_space})...", flush=True)
            ps = PinnedSpace(svd_space, token=HF_TOKEN if HF_TOKEN else None)
            up_img = ps.upload(img_file)
            out = ps.call("video", [up_img, 42 + index, True, 85, 8, 1.2, 1, 576, 1024, 4])
            ps.download_video(out, out_raw_video)
            print(f"🎉 تم تحريك المشهد {index + 1} إلى فيديو حقيقي بنجاح عبر {svd_space}!", flush=True)
            return True
        except Exception as e:
            print(f"انتقال للمحرك التالي بعد {svd_space}: {str(e)[:90]}", flush=True)

    return False


def render_subtitle_phrase_png(phrase_text, png_path):
    """رسم ترجمة سينمائية أنيقة بدون صناديق ضخمة مزعجة مع ضمان اتجاه الحروف العربية 100%"""
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # استخدام Layout.BASIC مع arabic_reshaper + bidi لضمان عدم انعكاس الحروف في أي إصدار من Pillow
    try:
        font = ImageFont.truetype(font_file, 62, layout_engine=ImageFont.Layout.BASIC)
        display_text = get_display(arabic_reshaper.reshape(phrase_text))
    except Exception:
        font = ImageFont.truetype(font_file, 62)
        display_text = phrase_text

    bbox = draw.textbbox((0, 0), display_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    x_pos = (1080 - w) // 2
    y_pos = 1520

    # كبسولة سينمائية ناعمة وخفيفة خلف النص فقط
    pad_x, pad_y = 32, 16
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=35,
        fill=(0, 0, 0, 145)
    )

    # ظل وحدود سوداء ناعمة لإبراز النص الأبيض/الذهبي
    for dx in (-4, -2, 0, 2, 4):
        for dy in (-4, -2, 0, 2, 4):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255))

    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 240, 100, 255))
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
    duration = max(float(probe.stdout.strip()), 3.4)

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, character_sheet, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_motion_video = f"base_motion_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        # تنعيم حركة الفيديو المولد بالذكاء الاصطناعي ورفع دقته إلى 1080x1920 بـ 30 إطاراً في الثانية
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,unsharp=3:3:0.6:3:3:0.0,setsar=1",
            "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "17",
            "-an", base_motion_video
        ], check=True)
    else:
        z_expr = "min(zoom+0.0022,1.25)" if index % 2 == 0 else "if(eq(on,1),1.25,max(zoom-0.0022,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.12:contrast=1.04,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},setsar=1"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_file,
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-an", base_motion_video
        ], check=True)

    clean_words = strip_diacritics(re.sub(r'["\'«»„“”*]', '', narration or "").strip()).split()
    video_file = f"scene_{index}.mp4"

    if not clean_words:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", base_motion_video, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "17",
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
        "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-t", str(duration), "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-shortest", video_file
    ], check=True)
    return video_file


def download_real_bgm(bgm_path):
    """تحميل موسيقى خلفية سينمائية/كوميدية حقيقية (Kevin MacLeod) بدلاً من الطنين الصناعي"""
    urls = list(ROYALTY_FREE_BGM_URLS)
    random.shuffle(urls)
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
            if r.ok and len(r.content) > 50000:
                with open(bgm_path, "wb") as f:
                    f.write(r.content)
                print(f"تم تحميل الموسيقى التصويرية السينمائية بنجاح: {url.split('/')[-1]}", flush=True)
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
            "title": f"{title[:80]} ✨🎬 #shorts",
            "description": f"{title}\n\nMusic by Kevin MacLeod (incompetech.com) Licensed under CC BY 3.0\n#انيميشن #قصص #حكايات #3d_animation #shorts",
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

    bgm_file = "bgm_track.mp3"
    if download_real_bgm(bgm_file):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", merged_video,
            "-stream_loop", "-1", "-i", bgm_file,
            "-filter_complex",
            "[1:a]volume=0.14[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
            "-level", "4.0", "-crf", "17", "-c:a", "aac", "-ar", "44100",
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
