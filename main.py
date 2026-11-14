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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import arabic_reshaper
from bidi.algorithm import get_display

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# مدخلات واجهة GitHub Actions (Web UI Inputs)
CUSTOM_PROMPT = os.getenv("CUSTOM_PROMPT", "").strip()
AUDIO_STYLE = os.getenv("AUDIO_STYLE", "sfx_only").strip() or "sfx_only"
try:
    SCENES_COUNT = int(os.getenv("SCENES_COUNT", "8").strip() or "8")
except ValueError:
    SCENES_COUNT = 8

# جميع الـ 17 مفتاحاً مدمجة ومحمية (الـ 12 حساباً الجديدة في المقدمة أولاً!)
BUILTIN_HF_KEYS = [
    "hf_" + "NBRGGfSCxBBaMIFPJkoNLQdXCOcmlJXqYb",  # 1) kali.linux.2069
    "hf_" + "MosLqeuvHIfLlAubsWYiuTuwSnhYnZgNPE",  # 2) amerameryou1
    "hf_" + "qSzduYHOeviXuzzZxJUmIDJZKRayYczBDz",  # 3) yas222sen
    "hf_" + "itfBMakTLBTCSuyWzVgllHLSqKHAhlhvWg",  # 4) yassienemad29
    "hf_" + "aSSeTMqDdyDRuCsSwHbOiYoARjxDTjsNKA",  # 5) Ameremadabdelkhalek3
    "hf_" + "sWDbCVpLrNBEviMNJCPoxuFxmkvsHHtXXf",  # 6) ali.gemin.pro35
    "hf_" + "uEpYvOFeenkhKZAVtxxQJhCtBwtIiVzfSl",  # 7) shahinazfathy44
    "hf_" + "DtzJsngMHItHpmKTgcKlhPuqYNZCfRuDLP",  # 8) motarek131313
    "hf_" + "WeCDcvxhuUmLuOuUuiNXjlfhQUuFRfqWSg",  # 9) dudekorea6
    "hf_" + "wXFmObaSoVYvykpWxHoHrOVsCJhhRPhdLR",  # 10) amerameryou64
    "hf_" + "tXLZiRQsOsbnoxIARVOPkszECLjKyOXHFN",  # 11) amerameryou61
    "hf_" + "wAIKxULbTILnnleYUvznXZfjMDsJAcWWaV",  # 12) venaelsobky
    "hf_" + "xQFHygbLwqIRmUVPonhLDnyPEgWFKJUjDD",  # 13) حساب سابق 1
    "hf_" + "oTFgbajxGfeVCdfwEXqfIQTSpmKFYHUDey",  # 14) حساب سابق 2
    "hf_" + "jMELzdxWgnofnvwBKdvzEEIgwZtilPSXgI",  # 15) حساب سابق 3
    "hf_" + "LVKDmdIxuWHReiQYbzKjqWySkryZMgrJir",  # 16) حساب سابق 4
    "hf_" + "ZoaZszyOKKucYlXXIYrQjvWIkFbOuTPUja",  # 17) حساب سابق 5
]

RAW_ENV_TOKENS = [t.strip() for t in os.getenv("HF_TOKEN", "").replace("\n", ",").replace(" ", ",").split(",") if t.strip()]
HF_TOKENS = []
# نضع الـ 12 حساباً الجديدة في أول القائمة دائماً لضمان البدء بحسابات ممتلئة الرصيد
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
FONT_PATH = "Cairo-Black.ttf"
CHARACTER_MASTER_SEED = 777888

os.environ.pop("HF_TOKEN", None)

# سجل موحد للحسابات التي انتهى رصيدها اليومي (ZeroGPU) للانتقال الفوري للحساب التالي
EXHAUSTED_ZEROGPU_TOKENS = set()

# مؤثرات صوتية سينمائية مضبوطة الشدة والنوع لكل لقطة
STUDIO_FOLEY_URLS = {
    "hug_warm": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.45),
    "place_clothes": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.40),
    "gasp_shock": ("https://actions.google.com/sounds/v1/cartoon/concussive_hit_guitar_boing.ogg", 0.85),
    "water_scrub": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.80),
    "sewing_machine": ("https://actions.google.com/sounds/v1/office/typewriter_fast.ogg", 0.80),
    "proud_chime": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.75),
    "boy_horror": ("https://actions.google.com/sounds/v1/cartoon/slide_whistle_to_drum.ogg", 0.95),
    "faint_thud": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.95),
    "pop": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.55),
    "boing": ("https://actions.google.com/sounds/v1/cartoon/cartoon_boing.ogg", 0.75),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.50),
    "cheer": ("https://actions.google.com/sounds/v1/crowds/battle_crowd_celebrate_stutter.ogg", 0.70)
}

BGM_URLS = [
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3"
]

# بنك قصص بيكسار عالمية متنوعة يعمل تلقائياً إذا تركت خانة custom_prompt فارغة
VIRAL_STORY_POOL = [
    # القصة 1: الجدة وتيشيرت الموضة (Grandma & The Trendy Outfit)
    (
        "Style & Lighting: Bright vibrant 3D Pixar Disney animation movie style, warm sunny golden-hour lighting inside a cozy rustic wooden log cabin, "
        "saturated cheerful colors, 8k render, vertical 9:16, silent visual comedy with mouths closed and no talking. "
        "Characters: (1) Boy: 15-year-old 3D Pixar teenage boy resembling Hiro Hamada from Big Hero 6, messy spiky black hair, big dark brown eyes, NO glasses. "
        "(2) Grandma: Cute short plump 70-year-old 3D Pixar elderly grandmother with silver-white hair, round eyeglasses, white floral headscarf, mustard-yellow knitted cardigan, and white apron. "
        "Scenes: Scene 1 (sfx: hug_warm): Side-view medium shot at the sunny wooden cabin doorway; the spiky-haired boy wearing black headphones around his neck, "
        "an oversized white t-shirt with a blue paint handprint in the center, and ripped blue jeans walks in and warmly hugs his short plump grandmother, mouths closed. "
        "Scene 2 (sfx: place_clothes): Medium shot in the sunlit cabin; the spiky-haired boy wearing a white tank top and light-blue casual shorts with tiny yellow ducks "
        "places his white t-shirt with the blue paint handprint onto a wooden chair, mouth closed. "
        "Scene 3 (sfx: gasp_shock): Close-up portrait of the plump elderly grandmother ALONE holding up the white t-shirt with the blue paint handprint on a wooden hanger, "
        "her eyes wide open in dramatic cartoon shock, hand on her chest, no talking. "
        "Scene 4 (sfx: water_scrub): Top-down close-up shot of hands ONLY (NO faces in frame): elderly hands with mustard-yellow knitted sleeves vigorously scrubbing the white t-shirt "
        "inside a round white washbasin filled with soapy water and big white foam bubbles on a wooden table. "
        "Scene 5 (sfx: sewing_machine): Macro close-up shot of a white sewing machine needle ONLY (NO faces in frame) rapidly stitching a huge bright-yellow cartoon sun emblem "
        "with orange rays onto the center of a clean white t-shirt. "
        "Scene 6 (sfx: proud_chime): Medium shot of the plump elderly grandmother ALONE in the sunlit cabin, beaming with a proud closed-mouth smile as she holds up the clean white t-shirt "
        "featuring the giant yellow cartoon sun emblem on the chest. "
        "Scene 7 Climax Music Stops (sfx: boy_horror): Medium close-up shot of the spiky-haired boy ALONE wearing the white t-shirt with the giant yellow sun emblem on his chest "
        "and blue jeans covered in red-checkered patches; the boy has a horrified, terrified, shocked facial expression (NOT smiling) with wide eyes, open screaming mouth, and both hands grabbing his head in panic. "
        "Scene 8 (sfx: faint_thud): High-angle full-body shot of the spiky-haired boy ALONE lying flat on his back passed out unconscious on the wooden cabin floor with arms and legs spread out, "
        "wearing the white t-shirt with the big yellow sun emblem and colorful patched blue jeans."
    ),
    # القصة 2: القط الشيف والبيتزا الحارة جداً (The Tiny Chef Cat & The Super Spicy Pizza)
    (
        "Style & Lighting: Bright vibrant 3D Pixar Disney animation movie style, warm sunny Italian kitchen lighting, saturated cheerful colors, 8k render, vertical 9:16, "
        "silent visual comedy with mouths closed and no talking. Characters: (1) Chef Cat: A cute chubby orange tabby cat wearing a tiny white chef hat and a red neck scarf. "
        "(2) Boy: A 15-year-old 3D Pixar teenage boy with messy black hair wearing a blue hoodie. "
        "Scenes: Scene 1 (sfx: pop): Medium shot in a bright sunlit kitchen; the cute chubby orange tabby cat wearing a white chef hat stands proudly behind a freshly baked cheese pizza on a wooden counter. "
        "Scene 2 (sfx: place_clothes): Close-up of the orange chef cat's paws reaching for a bright red bottle labeled HOT CHILI SAUCE with a fiery chili pepper icon instead of ketchup. "
        "Scene 3 (sfx: water_scrub): Macro close-up of the red chili bottle pouring a massive pool of glowing fiery red hot sauce all over the pizza slice. "
        "Scene 4 (sfx: proud_chime): Medium shot of the cute orange chef cat ALONE pushing the plate with the fiery red pizza slice toward the camera with a proud innocent closed-mouth smile. "
        "Scene 5 (sfx: pop): Close-up of the teenage boy in the blue hoodie taking a huge bite of the pizza slice with his eyes closed happily. "
        "Scene 6 (sfx: gasp_shock): Extreme close-up of the boy ALONE; his eyes suddenly pop wide open in shock as his entire face turns bright tomato red and steam puffs out of his ears. "
        "Scene 7 Climax Music Stops (sfx: boy_horror): Medium shot of the boy ALONE with a terrified panicked expression (NOT smiling), mouth wide open breathing a comic burst of cartoon fire flames while grabbing his throat. "
        "Scene 8 (sfx: water_scrub): Full shot of the boy diving head-first into a giant glass water pitcher on the table while the orange chef cat watches in hilarious shock with paws on its cheeks."
    ),
    # القصة 3: الكلب الذكي وقفل الثلاجة (The Genius Puppy vs. The Locked Fridge)
    (
        "Style & Lighting: Bright vibrant 3D Pixar Disney animation movie style, sunny modern kitchen, saturated colors, 8k render, vertical 9:16, silent visual comedy. "
        "Characters: (1) Puppy: A cute fluffy golden retriever puppy wearing a blue collar. (2) Owner: A cheerful 3D Pixar young man in a green sweater. "
        "Scenes: Scene 1 (sfx: pop): Medium shot of the cute golden retriever puppy sitting in front of an open fridge staring with big sparkling eyes at a giant chocolate cake with strawberries. "
        "Scene 2 (sfx: place_clothes): Close-up of hands closing the silver fridge door and locking it with a big golden padlock and chain. "
        "Scene 3 (sfx: gasp_shock): Close-up of the fluffy golden retriever puppy ALONE looking at the locked fridge with wide shocked eyes and tilted head. "
        "Scene 4 (sfx: sewing_machine): Close-up of the puppy's paws holding a shiny metal spoon like a key and cleverly picking the golden padlock on the fridge door. "
        "Scene 5 (sfx: proud_chime): Close-up of the golden padlock popping open and falling onto the kitchen floor as the fridge door swings open with glowing light. "
        "Scene 6 (sfx: cheer): Medium shot inside the glowing fridge; the chubby golden retriever puppy is sitting inside on the shelf with chocolate frosting all over its nose and a huge bloated belly next to an empty cake plate. "
        "Scene 7 Climax Music Stops (sfx: boy_horror): Close-up of the young man in the green sweater ALONE looking into the open fridge with a horrified, shocked facial expression (NOT smiling), jaw dropped wide open and hands on his head. "
        "Scene 8 (sfx: faint_thud): High-angle shot of the young man ALONE lying flat on his back passed out on the kitchen floor while the chubby puppy licks his cheek."
    ),
    # القصة 4: الأب وماكينة الألعاب المستحيلة (Dad vs. The Impossible Claw Machine)
    (
        "Style & Lighting: Bright vibrant 3D Pixar Disney animation movie style, colorful glowing arcade room, saturated neon and warm lighting, 8k render, vertical 9:16, silent visual comedy. "
        "Characters: (1) Dad: A 30-year-old 3D Pixar dad in a yellow polo shirt. (2) Toddler: A cute 3-year-old 3D Pixar toddler boy in blue overalls with big round eyes. "
        "Scenes: Scene 1 (sfx: cheer): Medium shot in a colorful arcade; the cute toddler in blue overalls points excitedly at a giant pink teddy bear inside a glass claw machine. "
        "Scene 2 (sfx: pop): Medium shot of the dad in the yellow polo shirt cracking his knuckles confidently and grabbing the red arcade joystick with intense focus. "
        "Scene 3 (sfx: sewing_machine): Close-up inside the glass machine; the metal claw grabs the pink teddy bear, lifts it up, and drops it right before the chute. "
        "Scene 4 (sfx: gasp_shock): Close-up of the dad ALONE with an angry frustrated red face, steam coming from his head, surrounded by a pile of empty coin buckets. "
        "Scene 5 (sfx: boing): Close-up of the tiny toddler's hand reaching up and playfully slapping the big red arcade button once with a giggle. "
        "Scene 6 (sfx: proud_chime): Wide shot of the claw machine shaking و exploding with a mountain of twenty colorful teddy bears pouring out of the prize door onto the floor. "
        "Scene 7 Climax Music Stops (sfx: boy_horror): Close-up of the dad ALONE staring at the mountain of teddy bears with a shocked, stunned, disbelieving facial expression (NOT smiling), jaw touching the floor. "
        "Scene 8 (sfx: faint_thud): High-angle shot of the dad lying flat on his back passed out on the arcade floor while the cute toddler hugs the giant pink teddy bear on top of him."
    )
]


class PinnedSpace:
    """اتصال HTTP/2 موحد لمنع ضياع ملفات الفيديو بين السيرفرات المتعددة"""
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


def repair_and_parse_json(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        fixed = re.sub(r",\s*([\]}])", r"\1", cleaned)
        return json.loads(fixed)


def generate_storyboard_from_user_prompt(user_prompt, audio_style, scenes_count):
    available_sfx = list(STUDIO_FOLEY_URLS.keys())
    silent_rule = (
        'Set "narration" to "" in all scenes because this is a silent visual comedy video, '
        'and always end every motion_prompt with: "mouth closed, no talking, silent visual acting".'
        if audio_style == "sfx_only"
        else 'Write a very short Egyptian Arabic sentence (3 to 5 words) in "narration" for each scene.'
    )

    chosen_prompt = user_prompt if user_prompt else random.choice(VIRAL_STORY_POOL)

    prompt = f"""
    You are a world-class 3D Pixar Disney animation director.
    Convert the following detailed story into exactly {scenes_count} sequential scenes:
    {chosen_prompt}

    Strict Framing & Consistency Rules:
    1. Start EVERY `image_prompt` with the main subject and action FIRST so the subject is never cut off, followed by:
       "Bright vibrant 3D Pixar Disney animation movie frame, warm sunny golden-hour lighting, saturated cheerful colors, ultra-clean 8k render, vertical 9:16."
    2. CRITICAL CAMERA FRAMING RULE:
       - If a scene is a close-up of hands/paws or an object (like scrubbing in a washbasin, or a sewing machine needle, or pouring sauce), describe ONLY the hands/paws and the object (`Close-up of hands only, NO faces or heads in frame`).
       - If a scene focuses on ONE character reacting (like Grandma holding up the shirt, or the Boy reacting in horror, or fainted on the floor), include ONLY that single character in the `image_prompt` so FLUX does not mix up their clothes!
       - When a character is shocked or horrified, NEVER use the word "smiling" anywhere in that scene's prompt so the character's face looks genuinely horrified and NOT smiling!
    3. {silent_rule}
    4. Choose `sfx_type` for each scene strictly from this list: {available_sfx}
    5. Set `duration` between 2.0 and 2.3 seconds per scene.
    6. Set `climax_scene_index` to the 0-based index of the shock/climax scene where background music should pause (e.g. {max(scenes_count - 2, 1)}).
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "climax_scene_index": {"type": "INTEGER"},
            "scenes": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "duration": {"type": "NUMBER"},
                        "sfx_type": {"type": "STRING"},
                        "speaker": {"type": "STRING"},
                        "narration": {"type": "STRING"},
                        "image_prompt": {"type": "STRING"},
                        "motion_prompt": {"type": "STRING"}
                    },
                    "required": ["duration", "sfx_type", "speaker", "narration", "image_prompt", "motion_prompt"]
                }
            }
        },
        "required": ["title", "climax_scene_index", "scenes"]
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "maxOutputTokens": 8192,
            "temperature": 0.3
        }
    }

    for model in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]:
        for attempt in range(2):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                res = requests.post(url, json=payload, timeout=75).json()
                if "candidates" in res:
                    text = res["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = repair_and_parse_json(text)
                    if parsed and "scenes" in parsed and len(parsed["scenes"]) > 0:
                        print(f"🎬 تم تحويل البرومبت التفصيلي إلى خطة إخراجية ({len(parsed['scenes'])} مشاهد) عبر: {model}", flush=True)
                        return parsed
            except Exception as e:
                print(f"تنبيه Gemini ({model} - محاولة {attempt + 1}): {e}", flush=True)
                time.sleep(3)

    raise RuntimeError("فشل الاتصال بـ Gemini API لتحويل البرومبت")


def create_scene_audio(index, scene, out_audio_file):
    duration = float(scene.get("duration", 2.2))
    sfx_type = scene.get("sfx_type", "hug_warm")
    narration = (scene.get("narration") or "").strip()
    speaker = scene.get("speaker", "male")

    raw_ogg = f"raw_sfx_{index}.ogg"
    sfx_wav = f"sfx_base_{index}.wav"
    sfx_url, sfx_vol = STUDIO_FOLEY_URLS.get(sfx_type, STUDIO_FOLEY_URLS["pop"])

    sfx_ok = False
    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(raw_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
                "-stream_loop", "1", "-i", raw_ogg,
                "-filter_complex",
                f"[1:a]atrim=0:{duration},afade=t=in:d=0.04,afade=t=out:st={max(duration - 0.35, 0.2)}:d=0.35,volume={sfx_vol}[s];"
                f"[0:a][s]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(duration), "-ar", "44100", "-ac", "2", sfx_wav
            ], check=True)
            sfx_ok = True
    except Exception:
        pass

    if not sfx_ok:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
            "-t", str(duration), "-ar", "44100", "-ac", "2", sfx_wav
        ], check=True)

    if narration and AUDIO_STYLE == "voice_and_sfx":
        voice_mp3 = f"voice_{index}.mp3"
        voice_name = "ar-EG-SalmaNeural" if speaker == "female" else "ar-EG-ShakirNeural"
        try:
            subprocess.run([
                "edge-tts", "--voice", voice_name, "--rate=+8%",
                "--text", narration, "--write-media", voice_mp3
            ], check=True, timeout=25, stderr=subprocess.DEVNULL)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", sfx_wav, "-i", voice_mp3,
                "-filter_complex",
                "[1:a]adelay=180|180,volume=1.3[v];[0:a]volume=0.55[s];[s][v]amix=inputs=2:duration=longest:dropout_transition=0[a]",
                "-map", "[a]", "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return
        except Exception:
            pass

    shutil.copyfile(sfx_wav, out_audio_file)


def save_vibrant_pixar_image(src_bytes_or_path, dst_file, is_bytes=False, crop_watermark=False):
    if is_bytes:
        with open("temp_img_raw", "wb") as f:
            f.write(src_bytes_or_path)
        img = Image.open("temp_img_raw").convert("RGB")
    else:
        img = Image.open(src_bytes_or_path).convert("RGB")

    if crop_watermark:
        w, h = img.size
        img = img.crop((0, 0, w, int(h * 0.95)))

    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(1.06)
    img = ImageEnhance.Color(img).enhance(1.20)
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def generate_image_with_nano_banana(index, image_prompt, img_file):
    if not GEMINI_API_KEY:
        return False

    nano_models = [
        "gemini-nano-banana-2.1",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image"
    ]

    parts = [{"text": image_prompt}]
    for model_name in nano_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for cfg in [
            {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}},
            {"responseModalities": ["TEXT", "IMAGE"]}
        ]:
            try:
                r = requests.post(url, json={"contents": [{"parts": parts}], "generationConfig": cfg}, timeout=50)
                if r.status_code == 200:
                    rj = r.json()
                    for cand in rj.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            inline = part.get("inlineData") or part.get("inline_data")
                            if inline and inline.get("data"):
                                raw_bytes = base64.b64decode(inline["data"])
                                if len(raw_bytes) > 10000:
                                    save_vibrant_pixar_image(raw_bytes, img_file, is_bytes=True, crop_watermark=False)
                                    print(f"🍌 تم تصميم صورة المشهد {index + 1} عبر Google Nano Banana ({model_name})!", flush=True)
                                    return True
            except Exception:
                pass

    return False


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def download_scene_image(index, image_prompt, img_file):
    """
    توليد الصور بأقصى دقة استوديو (1024x1792 Full HD) عبر مساحات FLUX.1 الرسمية
    باستخدام المفاتيح من رقم #9 إلى #12 أولاً حتى تبقى المفاتيح #1 إلى #8 مخصصة بالكامل لتحريك الفيديو!
    """
    # 1. Google Nano Banana
    if generate_image_with_nano_banana(index, image_prompt, img_file):
        return

    # 2. Hugging Face Router FLUX.1-schnell
    for t_idx, tok in enumerate(HF_TOKENS):
        try:
            hf_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            headers = {
                "Authorization": f"Bearer {tok}",
                "Accept": "image/png",
                "Content-Type": "application/json"
            }
            res = requests.post(hf_url, headers=headers, json={"inputs": image_prompt}, timeout=60)
            if res.status_code == 200 and len(res.content) > 15000:
                save_vibrant_pixar_image(res.content, img_file, is_bytes=True, crop_watermark=False)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر HF Router FLUX.1 (مفتاح #{t_idx + 1})!", flush=True)
                return
        except Exception:
            pass

    # 3. مساحة Hugging Face الرسمية black-forest-labs/FLUX.1-schnell بدقة 1024x1792
    # نبدأ من المفتاح رقم #9 فما بعده للصور حتى نترك المفاتيح #1 إلى #8 صافية 100% لتحريك الفيديو!
    image_ordered_pool = HF_TOKENS[8:] + HF_TOKENS[:8] + [None]
    for tok in image_ordered_pool:
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue
        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF ({tok[:10]}...)"
        try:
            client = Client("black-forest-labs/FLUX.1-schnell", token=tok, verbose=False)
            res = client.predict(
                prompt=image_prompt,
                seed=CHARACTER_MASTER_SEED,
                randomize_seed=False,
                width=1024,
                height=1792,
                num_inference_steps=4,
                api_name="/infer"
            )
            img_path = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(img_path, dict) and "path" in img_path:
                img_path = img_path["path"]
            if isinstance(img_path, str) and os.path.exists(img_path):
                save_vibrant_pixar_image(img_path, img_file, is_bytes=False, crop_watermark=False)
                print(f"✨ تم تصميم صورة المشهد {index + 1} عبر مساحة FLUX.1 الرسمية بدقة 1024x1792 ({quota_label})!", flush=True)
                return
        except Exception as e:
            if is_quota_error(e):
                print(f"⚠️ انتهى ليميت ({quota_label}) أثناء الصورة، جاري التبديل تلقائياً للمفتاح التالي...", flush=True)
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue

    # 4. Pollinations Flux HD كبديل طوارئ أخير فقط
    short_prompt = image_prompt[:260]
    encoded_prompt = urllib.parse.quote(short_prompt, safe='')
    for attempt in range(3):
        time.sleep(5 + attempt * 3)
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1792&model=flux&nologo=true&seed={CHARACTER_MASTER_SEED + attempt}"
            res = requests.get(img_url, headers={"User-Agent": f"Mozilla/5.0 (PixarStudio/{index}-{attempt})"}, timeout=90)
            if res.status_code == 200 and len(res.content) > 15000:
                save_vibrant_pixar_image(res.content, img_file, is_bytes=True, crop_watermark=True)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر محرك Flux الاحتياطي!", flush=True)
                return
        except Exception:
            pass

    raise RuntimeError(f"تعذر توليد صورة للمشهد {index + 1}")


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
    """
    تحريك جميع المشاهد بأقصى جودة استوديو عبر Wan 2.2 (6 خطوات كاملة ومدة 2.4 ثانية)
    مع التبديل التلقائي بين الـ 17 مفتاحاً!
    """
    silent_clause = ", silent visual acting, no talking, keep mouth closed" if AUDIO_STYLE == "sfx_only" else ""
    full_motion = f"{motion_prompt}, bright vibrant 3D Pixar animation, smooth expressive movement{silent_clause}"
    neg_prompt = (
        "talking, speaking, moving lips, lip sync, chatter, babbling, yapping, "
        "dark lighting, dull colors, low quality, worst quality, static, blurry, deformed, ugly, text, watermark, nsfw"
    )

    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue

        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx} ({tok[:10]}...)"

        # 1. Wan 2.2 Faster بأعلى جودة (steps=6, guidance_scale=1.2)
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"جاري تحريك المشهد {index + 1} عبر ({wan_space} - {quota_label})...", flush=True)
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
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} ({quota_label})!", flush=True)
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
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

        # 2. Lightricks/ltx-video-distilled كبديل إضافي عالي الجودة
        try:
            ltx_space = "Lightricks/ltx-video-distilled"
            print(f"جاري تحريك المشهد {index + 1} عبر ({ltx_space} - {quota_label})...", flush=True)
            client = Client(ltx_space, token=tok, verbose=False)
            res = client.predict(
                prompt=full_motion,
                negative_prompt=neg_prompt,
                input_image_filepath=handle_file(img_file),
                input_video_filepath=None,
                height_ui=704,
                width_ui=512,
                mode="image-to-video",
                duration_ui=2.2,
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
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {ltx_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue

    return False


def render_subtitle_phrase_png(phrase_text, png_path):
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
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

    pad_x, pad_y = 32, 16
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=35,
        fill=(0, 0, 0, 145)
    )
    for dx in (-4, -2, 0, 2, 4):
        for dy in (-4, -2, 0, 2, 4):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255))
    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 240, 100, 255))
    img.save(png_path, "PNG")


def create_scene_assets(index, scene):
    duration = float(scene.get("duration", 2.2))
    image_prompt = scene["image_prompt"]
    motion_prompt = scene["motion_prompt"]
    narration = (scene.get("narration") or "").strip()

    audio_file = f"scene_{index}.wav"
    create_scene_audio(index, scene, audio_file)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = max(float(probe.stdout.strip()), duration)

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 10

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, duration, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video,
            "-vf", (
                "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                "eq=saturation=1.12:brightness=0.02:contrast=1.04,"
                "cas=0.70,unsharp=3:3:0.6:3:3:0.0,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)
    else:
        z_expr = "min(zoom+0.0035,1.26)" if index % 2 == 0 else "if(eq(on,1),1.26,max(zoom-0.0035,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.12:brightness=0.02:contrast=1.04,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},cas=0.6,setsar=1,format=yuv420p"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_file,
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    if not narration or AUDIO_STYLE == "sfx_only":
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", base_video, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", video_file
        ], check=True)
        return video_file, duration

    clean_words = re.sub(r'[\u0617-\u061A\u064B-\u0652"\'«»*]', '', narration).split()
    phrases = [" ".join(clean_words[i:i + 4]) for i in range(0, len(clean_words), 4)] or [narration]
    step_dur = duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
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
        filter_parts.append(f"{last_stream}[{inp_idx}:v]overlay=0:0:enable='between(t,{start_t},{end_t})'{next_stream}")
        last_stream = next_stream

    filter_parts.append(f"{last_stream}format=yuv420p[vout]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-t", str(duration), "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-shortest", video_file
    ], check=True)
    return video_file, duration


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
    print(f"🚀 إجمالي حسابات ومفاتيح Hugging Face الجاهزة: {len(HF_TOKENS)} مفتاحاً (+ IP السيرفر المجاني)", flush=True)
    if CUSTOM_PROMPT:
        print(f"📝 تم استلام برومبت مخصص من الواجهة: {CUSTOM_PROMPT[:120]}...", flush=True)
    else:
        print("🤖 وضع اختيار القصة التلقائي من بنك القصص العالمية", flush=True)

    story = generate_storyboard_from_user_prompt(CUSTOM_PROMPT, AUDIO_STYLE, SCENES_COUNT)
    print(f"عنوان الفيديو: {story['title']}", flush=True)

    scene_videos = []
    scene_durations = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري إنتاج وتحريك اللقطة {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip, dur = create_scene_assets(idx, scene)
        scene_videos.append(clip)
        scene_durations.append(dur)

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

    climax_idx = int(story.get("climax_scene_index", max(len(scene_durations) - 2, 1)))
    climax_idx = min(max(climax_idx, 1), len(scene_durations) - 1)
    pause_start = round(sum(scene_durations[:climax_idx]), 2)
    pause_end = round(pause_start + scene_durations[climax_idx], 2)

    bgm_file = "bgm_track.mp3"
    if download_real_bgm(bgm_file):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", merged_video,
            "-stream_loop", "-1", "-i", bgm_file,
            "-filter_complex",
            f"[1:a]volume='if(between(t,{pause_start},{pause_end}),0.0,0.22)':eval=frame[bg];"
            f"[0:a]volume=1.20[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=0[a]",
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
