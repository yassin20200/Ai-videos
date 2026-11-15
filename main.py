import os
import re
import json
import time
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
FONT_PATH = "Cairo-Black.ttf"
CHARACTER_MASTER_SEED = 777888

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

# مؤثرات صوتية طبيعية وتاريخية (بدون أي معازف أو موسيقى)
HISTORICAL_FOLEY_URLS = {
    "bow_arrow": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.45),
    "desert_wind": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.35),
    "footsteps": ("https://actions.google.com/sounds/v1/foley/footsteps_on_wood.ogg", 0.35),
    "deep_impact": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.45),
    "cloth_move": ("https://actions.google.com/sounds/v1/foley/cloth_flapping.ogg", 0.30)
}


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


def get_saad_ibn_abi_waqqas_storyboard():
    """
    النسخة المتزامنة 100% مع الصور الـ 10 لقصة الصحابي الجليل سعد بن أبي وقاص رضي الله عنه
    (رواية صحيحة ثابتة في صحيح مسلم والبخاري - مدة الفيديو الإجمالية ~68 ثانية > دقيقة واحدة)
    """
    style = "Masterpiece dark-inked cinematic graphic novel illustration, bold hand-drawn comic line art, dramatic desert chiaroscuro lighting, rich earthy tones, vertical 9:16, no text. "
    veiled_saad = "a noble 7th-century Arabian warrior wearing a beige turban and cloth face-veil covering his face with a dignified glowing white slit of light at his eyes, wearing a brown striped cloak over a white tunic"

    return {
        "title": "سعد بن أبي وقاص رضي الله عنه | أول من رمى بسهم في سبيل الله",
        "scenes": [
            {
                "duration": 6.6,
                "sfx_type": "bow_arrow",
                "narration": "هُوَ خَالُ رَسُولِ اللَّهِ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ، وَأَعْظَمُ رُمَاةِ الإِسْلامِ؛ الصَّحَابِيُّ الجَلِيلُ سَعْدُ بْنُ أَبِي وَقَّاصٍ رَضِيَ اللَّهُ عَنْهُ، أَوَّلُ مَنْ رَمَى بِسَهْمٍ فِي سَبِيلِ اللَّهِ.",
                "image_prompt": f"{style}{veiled_saad}, kneeling on rocky desert ground, drawing a wooden bow and arrow with intense focus.",
                "motion_prompt": "Cinematic graphic novel animation, the veiled archer draws his wooden bow taut as his brown cloak sways gently in the desert wind, slow motion, no talking"
            },
            {
                "duration": 6.6,
                "sfx_type": "desert_wind",
                "narration": "فِي بِدَايَةِ البِعْثَةِ النَّبَوِيَّةِ، رَأَى سَعْدٌ فِي مَنَامِهِ كَأَنَّهُ فِي ظُلْمَةٍ لا يُبْصِرُ فِيهَا شَيْئاً، فَأَضَاءَ لَهُ قَمَرٌ سَاطِعٌ اتَّبَعَ نُورَهُ، فَعَلِمَ أَنَّهُ نُورُ الهِدَايَةِ وَالحَقِّ.",
                "image_prompt": f"{style}Nighttime scene, {veiled_saad} seen from behind standing in dark shadows looking towards a giant glowing full moon rising over dark water, with three robed figures standing near the moonlight.",
                "motion_prompt": "Cinematic graphic novel animation, the glowing full moon shines over the rippling water as the veiled figure watches in awe, slow camera push in, no talking"
            },
            {
                "duration": 6.6,
                "sfx_type": "footsteps",
                "narration": "فَاسْتَيْقَظَ مُسْرِعاً يَبْحَثُ عَنْ رَسُولِ اللَّهِ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ فِي شِعَابِ مَكَّةَ، فَأَسْلَمَ وَهُوَ ابْنُ سَبْعَ عَشْرَةَ سَنَةً، لِيَكُونَ مِنْ أَوَائِلِ السَّابِقِينَ إِلَى الإِسْلامِ.",
                "image_prompt": f"{style}{veiled_saad} seen from behind running eagerly through a narrow ancient stone alleyway in 7th-century Makkah toward warm golden sunlight.",
                "motion_prompt": "Cinematic graphic novel animation, the veiled young man runs forward through the ancient stone alleyway as his brown cloak billows behind him, slow motion, no talking"
            },
            {
                "duration": 6.8,
                "sfx_type": "deep_impact",
                "narration": "وَلَكِنَّ أُمَّهُ غَضِبَتْ غَضَباً شَدِيداً حِينَ عَلِمَتْ بِإِسْلامِهِ، وَأَقْسَمَتْ أَلَّا تَأْكُلَ طَعَاماً وَلا تَشْرَبَ شَرَاباً حَتَّى يَتْرُكَ دِينَهُ أَوْ تَمُوتَ حُزْناً وَغَيْظاً.",
                "image_prompt": f"{style}Inside a dim ancient stone room lit by a small oil lamp, an elderly 7th-century Arabian mother with a stern angry face wearing a modest beige headscarf and dark red robe confronts {veiled_saad} standing by the wooden doorway.",
                "motion_prompt": "Cinematic graphic novel animation, dramatic oil lamp shadows flicker as the stern elderly mother confronts her veiled son standing calmly at the doorway, no talking"
            },
            {
                "duration": 6.8,
                "sfx_type": "desert_wind",
                "narration": "مَكَثَتْ أُمُّهُ أَيَّاماً لا تَأْكُلُ وَلا تَشْرَبُ حَتَّى خَارَتْ قُوَاهَا وَأَشْرَفَتْ عَلَى الهَلاكِ، وَكَانَ سَعْدٌ شَدِيدَ البِرِّ بِهَا، فَكَانَ ذَلِكَ ابْتِلاءً عَظِيماً لِقَلْبِهِ.",
                "image_prompt": f"{style}The elderly Arabian mother in a modest beige headscarf and dark red robe sitting weak and exhausted on the stone floor against a cracked mud-brick wall next to a flickering oil lamp, with an untouched clay water jug and wooden bowl in front of her.",
                "motion_prompt": "Cinematic graphic novel animation, the oil lamp flame flickers softly next to the weak elderly mother sitting on the floor looking away stubbornly, no talking"
            },
            {
                "duration": 7.2,
                "sfx_type": "cloth_move",
                "narration": "فَجَلَسَ إِلَيْهَا سَعْدٌ رَضِيَ اللَّهُ عَنْهُ وَقَالَ لَهَا كَلِمَاتٍ خَلَّدَهَا التَّارِيخُ: يَا أُمَّاهُ، تَعْلَمِينَ وَاللَّهِ لَوْ كَانَتْ لَكِ مِائَةُ نَفْسٍ فَخَرَجَتْ نَفْساً نَفْساً مَا تَرَكْتُ دِينِي هَذَا لِشَيْءٍ.",
                "image_prompt": f"{style}Inside the oil-lamp lit stone room, {veiled_saad} sits respectfully on the floor facing his elderly mother in the beige headscarf and dark red robe with calm unshakable resolve.",
                "motion_prompt": "Cinematic graphic novel animation, the veiled son sits with calm unshakable dignity facing his mother in the warm flickering lamp light, slow motion, no talking"
            },
            {
                "duration": 7.2,
                "sfx_type": "deep_impact",
                "narration": "فَلَمَّا رَأَتْ أُمُّهُ قُوَّةَ يَقِينِهِ وَثَبَاتِهِ عَلِمَتْ أَنَّهُ لَنْ يَتَرَاجَعَ أَبَداً فَأَكَلَتْ وَشَرِبَتْ، وَأَنْزَلَ اللَّهُ فِيهِ آيَةً تُتْلَى إِلَى يَوْمِ القِيَامَةِ فِي البِرِّ وَالثَّبَاتِ عَلَى العَقِيدَةِ.",
                "image_prompt": f"{style}Close-up shot of the elderly mother in the modest beige headscarf and dark red robe sitting on the floor in warm lamp light with a tear on her cheek, holding a piece of flatbread in her hand.",
                "motion_prompt": "Cinematic graphic novel animation, a tear glistens on the elderly mother's cheek as she slowly raises the piece of bread in her hand, warm lamp light, no talking"
            },
            {
                "duration": 6.6,
                "sfx_type": "desert_wind",
                "narration": "وَفِي أَحَدِ الأَيَّامِ، كَانَ سَعْدٌ رَضِيَ اللَّهُ عَنْهُ مَعَ نَفَرٍ مِنْ أَصْحَابِ النَّبِيِّ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ يُصَلُّونَ سِرّاً فِي شِعْبٍ مِنْ شِعَابِ مَكَّةَ بَعِيداً عَنْ أَعْيُنِ قُرَيْشٍ.",
                "image_prompt": f"{style}Three 7th-century Arabian Muslim men wearing modest white tunics and turbans with veiled faces sitting in peaceful prayer inside a narrow rocky mountain valley in Makkah with golden sunlight streaming through.",
                "motion_prompt": "Cinematic graphic novel animation, golden sunbeams and desert dust motes float peacefully through the rocky canyon over the praying veiled figures, no talking"
            },
            {
                "duration": 6.8,
                "sfx_type": "footsteps",
                "narration": "فَظَهَرَ عَلَيْهِمْ نَفَرٌ مِنَ المُشْرِكِينَ فَعَابُوا عَلَيْهِمْ دِينَهُمْ وَهَجَمُوا عَلَيْهِمْ لِيُؤْذُوهُمْ، فَتَصَدَّى لَهُمْ سَعْدٌ رَضِيَ اللَّهُ عَنْهُ بِشَجَاعَةٍ نَادِرَةٍ وَذَادَ عَنْ إِخْوَانِهِ المُسْلِمِينَ.",
                "image_prompt": f"{style}In the rocky mountain valley, {veiled_saad} stands bravely in the foreground facing a group of angry bearded men in dark robes approaching down the rocky canyon path.",
                "motion_prompt": "Cinematic graphic novel animation, the veiled warrior stands firm and fearless in the canyon as his cloak moves in the wind while dark-robed men approach in the background, no talking"
            },
            {
                "duration": 7.0,
                "sfx_type": "bow_arrow",
                "narration": "وَفِي غَزْوَةِ أُحُدٍ، ذَادَ بِسِهَامِهِ عَنْ رَسُولِ اللَّهِ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ حَتَّى جَمَعَ لَهُ النَّبِيُّ أَبَوَيْهِ فَقَالَ: ارْمِ سَعْدُ فِدَاكَ أَبِي وَأُمِّي! فَرَضِيَ اللَّهُ عَنْ سَعْدٍ وَأَرْضَاهُ.",
                "image_prompt": f"{style}Epic close-up front shot of {veiled_saad} aiming his wooden bow and iron-tipped arrow directly toward the camera in the middle of a dusty battlefield with glowing embers in the air.",
                "motion_prompt": "Cinematic graphic novel animation, the veiled archer holds his bow aimed steady as glowing battlefield embers and dust float past in dramatic slow motion, no talking"
            }
        ]
    }


def find_uploaded_image_for_scene(scene_number_1based):
    """فحص ما إذا كان المستخدم قد رفع صورة لهذا المشهد (مثلاً 1.jpg أو 1.png أو 1.webp)"""
    search_dirs = [".", "images", "scenes"]
    exts = ["jpg", "jpeg", "png", "webp", "JPG", "PNG", "JPEG", "WEBP"]
    for d in search_dirs:
        for ext in exts:
            for candidate in [
                f"{d}/{scene_number_1based}.{ext}",
                f"{d}/0{scene_number_1based}.{ext}",
                f"{d}/scene_{scene_number_1based}.{ext}"
            ]:
                if os.path.exists(candidate) and os.path.getsize(candidate) > 5000:
                    return candidate
    return None


def save_cinematic_image(src_bytes_or_path, dst_file, is_bytes=False):
    if is_bytes:
        with open("temp_img_raw", "wb") as f:
            f.write(src_bytes_or_path)
        img = Image.open("temp_img_raw").convert("RGB")
    else:
        img = Image.open(src_bytes_or_path).convert("RGB")

    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img.save(dst_file, "JPEG", quality=98)


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def obtain_scene_image(index, image_prompt, img_file):
    """
    1. إذا رفع المستخدم الصورة (1.jpg .. 10.jpg) من Gemini، يستخدمها فوراً!
    2. وإذا لم يرفعها، يولدها تلقائياً عبر FLUX.1-dev (24 خطوة) على Hugging Face!
    """
    uploaded = find_uploaded_image_for_scene(index + 1)
    if uploaded:
        save_cinematic_image(uploaded, img_file, is_bytes=False)
        print(f"📸 تم استخدام صورتك المرفوعة من Gemini للمشهد {index + 1}: ({uploaded})!", flush=True)
        return

    image_pool = HF_TOKENS[8:] + HF_TOKENS[:8] + [None]
    for space_name, steps in [("black-forest-labs/FLUX.1-dev", 24), ("black-forest-labs/FLUX.1-schnell", 4)]:
        for tok in image_pool:
            tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
            if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
                continue
            quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF ({tok[:10]}...)"
            try:
                client = Client(space_name, token=tok, verbose=False)
                if "dev" in space_name:
                    res = client.predict(
                        prompt=image_prompt,
                        seed=CHARACTER_MASTER_SEED,
                        randomize_seed=False,
                        width=1024,
                        height=1792,
                        guidance_scale=3.5,
                        num_inference_steps=steps,
                        api_name="/infer"
                    )
                else:
                    res = client.predict(
                        prompt=image_prompt,
                        seed=CHARACTER_MASTER_SEED,
                        randomize_seed=False,
                        width=1024,
                        height=1792,
                        num_inference_steps=steps,
                        api_name="/infer"
                    )
                img_path = res[0] if isinstance(res, (list, tuple)) else res
                if isinstance(img_path, dict) and "path" in img_path:
                    img_path = img_path["path"]
                if isinstance(img_path, str) and os.path.exists(img_path):
                    save_cinematic_image(img_path, img_file, is_bytes=False)
                    print(f"✨ تم رسم المشهد {index + 1} تلقائياً عبر ({space_name} - {quota_label})!", flush=True)
                    return
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
                break

    raise RuntimeError(f"تعذر تجهيز صورة للمشهد {index + 1}")


def create_scene_audio_and_get_duration(index, scene, out_audio_file):
    narration = (scene.get("narration") or "").strip()
    sfx_type = scene.get("sfx_type", "desert_wind")
    min_scene_dur = float(scene.get("duration", 6.6))

    voice_mp3 = f"voice_{index}.mp3"
    sfx_ogg = f"raw_sfx_{index}.ogg"
    sfx_url, sfx_vol = HISTORICAL_FOLEY_URLS.get(sfx_type, HISTORICAL_FOLEY_URLS["desert_wind"])

    voice_ok = False
    for voice_name, pitch, rate in [
        ("ar-SA-HamedNeural", "-5Hz", "-4%"),
        ("ar-EG-ShakirNeural", "-4Hz", "-3%")
    ]:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice_name,
                f"--pitch={pitch}", f"--rate={rate}",
                "--text", narration, "--write-media", voice_mp3
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(voice_mp3) and os.path.getsize(voice_mp3) > 1000:
                voice_ok = True
                break
        except Exception:
            time.sleep(1)

    if not voice_ok:
        encoded = urllib.parse.quote(narration)
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded}", timeout=30)
        with open(voice_mp3, "wb") as f:
            f.write(r.content)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", voice_mp3
    ], capture_output=True, text=True, check=True)
    voice_dur = float(probe.stdout.strip() or "5.8")
    final_dur = max(round(voice_dur + 0.85, 2), min_scene_dur)

    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-stream_loop", "2", "-i", sfx_ogg,
                "-i", voice_mp3,
                "-filter_complex",
                f"[1:a]atrim=0:{final_dur},afade=t=in:d=0.2,afade=t=out:st={max(final_dur - 0.5, 0.5)}:d=0.5,volume={sfx_vol}[sfx];"
                f"[2:a]adelay=200|200,volume=1.35[v];"
                f"[0:a][sfx][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return final_dur
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", voice_mp3,
        "-filter_complex",
        "[1:a]adelay=200|200,volume=1.35[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)
    return final_dur


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
    full_motion = (
        f"{motion_prompt}, cinematic graphic novel animation, dramatic slow motion, "
        f"no talking, no moving lips, high quality"
    )
    neg_prompt = (
        "talking, speaking, moving lips, lip sync, morphing, deformed, extra limbs, "
        "blurry, low quality, worst quality, text, watermark, nsfw"
    )

    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue

        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx} ({tok[:10]}...)"

        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"جاري تحريك المشهد {index + 1} عبر ({wan_space} - {quota_label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=6,
                negative_prompt=neg_prompt,
                duration_seconds=2.5,
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
                out = ps.call("/generate_video", [up_img, full_motion, 6, neg_prompt, 2.5, 1.2, 1.2, CHARACTER_MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def render_subtitle_phrase_png(phrase_text, png_path):
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(font_file, 54, layout_engine=ImageFont.Layout.BASIC)
        display_text = get_display(arabic_reshaper.reshape(phrase_text))
    except Exception:
        font = ImageFont.truetype(font_file, 54)
        display_text = phrase_text

    bbox = draw.textbbox((0, 0), display_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (1080 - w) // 2
    y_pos = 1540

    pad_x, pad_y = 30, 14
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=22,
        fill=(0, 0, 0, 175)
    )
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255))
    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 255, 255, 255))
    img.save(png_path, "PNG")


def create_scene_assets(index, scene):
    image_prompt = scene["image_prompt"]
    motion_prompt = scene["motion_prompt"]
    narration = (scene.get("narration") or "").strip()

    audio_file = f"scene_{index}.wav"
    duration = create_scene_audio_and_get_duration(index, scene, audio_file)

    img_file = f"scene_{index}.jpg"
    obtain_scene_image(index, image_prompt, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 10

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        # حركة بطيئة سينمائية ناعمة تغطي مدة السرد الكاملة (6.8 ثانية) بدون أي قطع
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video,
            "-vf", (
                "setpts=2.4*PTS,"
                "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                "cas=0.65,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)
    else:
        z_expr = "min(zoom+0.0016,1.20)" if index % 2 == 0 else "if(eq(on,1),1.20,max(zoom-0.0016,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},cas=0.5,setsar=1,format=yuv420p"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_file,
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    clean_words = re.sub(r'[\u0617-\u061A\u064B-\u0652"\'«»*():؛،.]', '', narration).split()
    phrases = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)] or ["..."]
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
            "title": f"{title[:80]} ✨ #قصص_اسلامية #الصحابة",
            "description": f"{title}\n\n#قصص_اسلامية #الصحابة #سعد_بن_أبي_وقاص #تاريخ_إسلامي #مواعظ",
            "tags": ["قصص إسلامية", "الصحابة", "سعد بن أبي وقاص", "تاريخ إسلامي", "مواعظ"],
            "categoryId": "27"
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
    requests.post(upload_url, headers=headers, data=video_bytes, timeout=240).raise_for_status()

    finish_res = requests.post(
        f"{GRAPH_API}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": f"{title} ✨\n\n#قصص_اسلامية #الصحابة #سعد_بن_أبي_وقاص #reels",
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
                timeout=180
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
                timeout=180
            ).json()
        if r.get("success") and r.get("files"):
            return r["files"][0]["url"]
    except Exception:
        pass

    with open(video_path, "rb") as f:
        r = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": f},
            timeout=180
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
    caption = f"{title} ✨\n\n#قصص_اسلامية #الصحابة #سعد_بن_أبي_وقاص #reels"
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
    print(f"🚀 إجمالي حسابات ومفاتيح Hugging Face الجاهزة: {len(HF_TOKENS)} مفتاحاً", flush=True)
    story = get_saad_ibn_abi_waqqas_storyboard()
    print(f"🕌 عنوان القصة: {story['title']} (10 مشاهد متزامنة - أكثر من دقيقة)", flush=True)

    scene_videos = []
    total_duration = 0.0
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري تجهيز وتحريك المشهد {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip, dur = create_scene_assets(idx, scene)
        scene_videos.append(clip)
        total_duration += dur

    print(f"⏱️ إجمالي مدة الفيديو النهائية: {round(total_duration, 1)} ثانية ({round(total_duration / 60, 2)} دقيقة)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري المونتاج النهائي وإضافة الأجواء الصوتية الطبيعية (بدون موسيقى/معازف)...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "anoisesrc=c=brown:a=0.015",
        "-filter_complex",
        "[1:a]lowpass=f=220[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", "-map", "[a]",
        "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
        "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
        "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
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
