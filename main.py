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
RECITER_NAME = os.getenv("RECITER_NAME", "Yasser_Ad-Dussary").strip() or "Yasser_Ad-Dussary"
QURAN_STORY = os.getenv("QURAN_STORY", "musa_parting_sea").strip() or "musa_parting_sea"

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

# إعداد مُشكّل الحروف العربية مع تعطيل الرموز المدمجة (support_ligatures=False) لمنع ظهور المربع ▯ في لفظ الجلالة "الله"
ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": True,
    "support_ligatures": False
})

# مجلدات القراء المشهورين في مكتبة القرآن العالمية (EveryAyah CDN)
RECITER_FOLDERS = {
    "Yasser_Ad-Dussary": ("Yasser_Ad-Dussary_128kbps", "ar.yasseraldossari", "الشيخ ياسر الدوسري"),
    "Maher_AlMuaiqly": ("MaherAlMuaiqly128kbps", "ar.mahermuaiqly", "الشيخ ماهر المعيقلي"),
    "Mishary_Alafasy": ("Alafasy_128kbps", "ar.alafasy", "الشيخ مشاري راشد العفاسي"),
    "Nasser_AlQatami": ("Nasser_Alqatami_128kbps", "ar.nasseralqatami", "الشيخ ناصر القطامي"),
    "AbdulBaset_Murattal": ("Abdul_Basit_Murattal_192kbps", "ar.abdulbasitmurattal", "الشيخ عبد الباسط عبد الصمد"),
    "Minshawy_Murattal": ("Minshawy_Murattal_128kbps", "ar.minshawi", "الشيخ محمد صديق المنشاوي")
}

# مؤثرات طبيعية هادئة جداً ترافق المشاهد (ماء، رياح، أمواج) بدون أي موسيقى
NATURE_FOLEY_URLS = {
    "desert_wind": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.18),
    "sea_waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.22),
    "water_parting": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.25),
    "staff_strike": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.35)
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


def get_quran_simulation_storyboard(story_key):
    """
    محاكاة بصرية سينمائية للآيات القرآنية الكريمة (10 مشاهد متزامنة مع تلاوة القارئ آية بآية)
    مع الالتزام الشرعي التام بعدم إظهار وجوه الأنبياء عليهم السلام نهائياً.
    """
    style = "Masterpiece dark-inked cinematic graphic novel illustration, bold hand-drawn comic line art, dramatic desert and ocean chiaroscuro lighting, rich earthy tones, vertical 9:16, no text, no watermarks. "
    _, _, reciter_ar = RECITER_FOLDERS.get(RECITER_NAME, RECITER_FOLDERS["Yasser_Ad-Dussary"])

    # سورة الشعراء (الآيات 60 إلى 68) - قصة نبي الله موسى عليه السلام وفلق البحر العظيم
    return {
        "title": f"كلا إن معي ربي سيهدين | محاكاة فلق البحر بصوت {reciter_ar}",
        "scenes": [
            {
                # المشهد 1: البسملة ومطلع القصة (الفاتحة آية 1 + تمهيد بصري)
                "surah": 1,
                "ayah": 1,
                "min_duration": 6.2,
                "sfx_type": "desert_wind",
                "subtitle_text": "بسم الله الرحمن الرحيم",
                "image_prompt": f"{style}A vast crowd of ancient travellers in modest historical robes walking seen strictly from behind across a misty desert valley at dawn towards the sea shore in the distance, no faces shown.",
                "motion_prompt": "Cinematic graphic novel animation, robed travellers walking forward seen from behind across the misty desert valley at dawn, slow motion, no talking"
            },
            {
                # المشهد 2: الشعراء آية 60
                "surah": 26,
                "ayah": 60,
                "min_duration": 6.2,
                "sfx_type": "desert_wind",
                "subtitle_text": "فأتبعوهم مشرقين",
                "image_prompt": f"{style}At sunrise, a massive ancient Egyptian army of war chariots and horses charging across the desert sand kicking up a huge storm of golden dust under the rising sun.",
                "motion_prompt": "Cinematic graphic novel animation, war chariots and horses charging across the desert as golden dust clouds billow in the sunrise light, slow motion"
            },
            {
                # المشهد 3: الشعراء آية 61
                "surah": 26,
                "ayah": 61,
                "min_duration": 7.5,
                "sfx_type": "sea_waves",
                "subtitle_text": "فلما تراءى الجمعان قال أصحاب موسى إنا لمدركون",
                "image_prompt": f"{style}A group of robed travellers standing trapped at the edge of a dark crashing sea beach, looking back at a massive wall of desert dust approaching in the distance.",
                "motion_prompt": "Cinematic graphic novel animation, dark ocean waves crash on the shore as the robed travellers robes billow in the wind, slow camera push in, no talking"
            },
            {
                # المشهد 4: الشعراء آية 62 (إخفاء الوجه تماماً - من الخلف فقط مع هالة ضوئية)
                "surah": 26,
                "ayah": 62,
                "min_duration": 7.0,
                "sfx_type": "sea_waves",
                "subtitle_text": "قال كلا إن معي ربي سيهدين",
                "image_prompt": f"{style}A noble robed figure seen strictly from BEHIND (back view only, NO face visible at all, head surrounded by a soft halo of white light), wearing a brown wool cloak over a beige tunic, standing firm at the edge of the crashing ocean waves holding a tall wooden staff.",
                "motion_prompt": "Cinematic graphic novel animation, the robed figure seen from behind stands firm holding the wooden staff as the brown cloak billows in the sea wind and waves crash ahead, no talking"
            },
            {
                # المشهد 5: الشعراء آية 63 (الجزء الأول - ضرب البحر بالعصا)
                "surah": 26,
                "ayah": 63,
                "trim_part": "first_half",
                "min_duration": 6.5,
                "sfx_type": "staff_strike",
                "subtitle_text": "فأوحينا إلى موسى أن اضرب بعصاك البحر",
                "image_prompt": f"{style}Close-up shot (NO face in frame): the tip of a rustic wooden staff striking the dark turbulent ocean water surface, sending a blinding shockwave of glowing white light and splashing water ripples across the sea.",
                "motion_prompt": "Cinematic graphic novel animation, the wooden staff strikes the dark water sending glowing ripples and splashing waves outward in dramatic slow motion"
            },
            {
                # المشهد 6: الشعراء آية 63 (الجزء الثاني - انفلاق البحر كالطود العظيم)
                "surah": 26,
                "ayah": 63,
                "trim_part": "second_half",
                "min_duration": 6.8,
                "sfx_type": "water_parting",
                "subtitle_text": "فانفلق فكان كل فرق كالطود العظيم",
                "image_prompt": f"{style}Breathtaking wide shot: the deep ocean miraculously parting into two colossal towering walls of rushing water like giant mountains on the left and right, revealing a wide dry rocky path down the middle lit by golden light.",
                "motion_prompt": "Cinematic graphic novel animation, two colossal towering walls of ocean water surge upward on both sides revealing a glowing dry path down the center in epic slow motion"
            },
            {
                # المشهد 7: الشعراء آية 64
                "surah": 26,
                "ayah": 64,
                "min_duration": 6.0,
                "sfx_type": "desert_wind",
                "subtitle_text": "وأزلفنا ثم الآخرين",
                "image_prompt": f"{style}Ancient war chariots pulled by dark horses rushing aggressively toward the entrance of the parted sea canyon between the two giant towering walls of water.",
                "motion_prompt": "Cinematic graphic novel animation, war chariots and horses rush forward into the canyon between the giant walls of water, dramatic slow motion"
            },
            {
                # المشهد 8: الشعراء آية 65
                "surah": 26,
                "ayah": 65,
                "min_duration": 6.8,
                "sfx_type": "sea_waves",
                "subtitle_text": "وأنجينا موسى ومن معه أجمعين",
                "image_prompt": f"{style}Silhouetted robed believers seen strictly from behind walking safely out of the parted sea onto the sunny rocky shore on the other side, led by the robed figure with the wooden staff seen strictly from behind.",
                "motion_prompt": "Cinematic graphic novel animation, silhouetted robed believers seen from behind walk safely onto the sunlit shore as golden light shines down, slow motion"
            },
            {
                # المشهد 9: الشعراء آية 66
                "surah": 26,
                "ayah": 66,
                "min_duration": 6.2,
                "sfx_type": "water_parting",
                "subtitle_text": "ثم أغرقنا الآخرين",
                "image_prompt": f"{style}The two colossal towering mountain walls of ocean water crashing back together with immense power, swallowing empty wooden war chariot wheels in swirling white foam and deep dark waves.",
                "motion_prompt": "Cinematic graphic novel animation, giant towering walls of ocean water crash together in a massive explosion of white foam and waves in dramatic slow motion"
            },
            {
                # المشهد 10: الشعراء آية 67 و 68
                "surah": 26,
                "ayah": 67,
                "extra_ayah": 68,
                "min_duration": 8.5,
                "sfx_type": "sea_waves",
                "subtitle_text": "إن في ذلك لآية وما كان أكثرهم مؤمنين • وإن ربك لهو العزيز الرحيم",
                "image_prompt": f"{style}Serene majestic landscape shot: the vast ocean now calm and peaceful after the storm, with glorious golden sunbeams breaking through dramatic clouds over the water and distant mountains, no people.",
                "motion_prompt": "Cinematic graphic novel animation, golden sunbeams shine through dramatic clouds over the calm rippling ocean water in peaceful slow motion"
            }
        ]
    }


def download_ayah_recitation_mp3(surah, ayah, dst_mp3):
    """تحميل التلاوة القرآنية الأصلية للآية الكريمة بصوت القارئ المختار من مكتبة القرآن الرسمية"""
    folder, alquran_edition, _ = RECITER_FOLDERS.get(RECITER_NAME, RECITER_FOLDERS["Yasser_Ad-Dussary"])

    # 1. المحاولة المباشرة عبر EveryAyah CDN الرسمي
    everyayah_url = f"https://everyayah.com/data/{folder}/{surah:03d}{ayah:03d}.mp3"
    try:
        r = requests.get(everyayah_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.ok and len(r.content) > 2000:
            with open(dst_mp3, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass

    # 2. البديل الرسمي عبر AlQuran Cloud CDN
    try:
        api_url = f"https://api.alquran.cloud/v1/ayah/{surah}:{ayah}/{alquran_edition}"
        rj = requests.get(api_url, timeout=20).json()
        audio_url = rj.get("data", {}).get("audio")
        if audio_url:
            r2 = requests.get(audio_url, timeout=30)
            if r2.ok and len(r2.content) > 2000:
                with open(dst_mp3, "wb") as f:
                    f.write(r2.content)
                return True
    except Exception:
        pass

    # 3. البديل الثالث بصوت الشيخ مشاري العفاسي المضمون
    fallback_url = f"https://everyayah.com/data/Alafasy_128kbps/{surah:03d}{ayah:03d}.mp3"
    r3 = requests.get(fallback_url, timeout=30)
    r3.raise_for_status()
    with open(dst_mp3, "wb") as f:
        f.write(r3.content)
    return True


def create_scene_quran_audio(index, scene, out_audio_file):
    """تجهيز صوت تلاوة الآية الكريمة مع المؤثر الطبيعي الهادئ وحساب المدة بالضبط (بين 65 و 80 ثانية إجمالاً)"""
    surah = int(scene["surah"])
    ayah = int(scene["ayah"])
    extra_ayah = scene.get("extra_ayah")
    trim_part = scene.get("trim_part")
    min_dur = float(scene.get("min_duration", 6.2))
    sfx_type = scene.get("sfx_type", "sea_waves")

    raw_ayah_mp3 = f"ayah_raw_{index}.mp3"
    download_ayah_recitation_mp3(surah, ayah, raw_ayah_mp3)

    if extra_ayah:
        extra_mp3 = f"ayah_extra_{index}.mp3"
        combined_mp3 = f"ayah_comb_{index}.mp3"
        download_ayah_recitation_mp3(surah, int(extra_ayah), extra_mp3)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ayah_mp3, "-i", extra_mp3,
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map", "[a]", combined_mp3
        ], check=True)
        shutil.copyfile(combined_mp3, raw_ayah_mp3)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", raw_ayah_mp3
    ], capture_output=True, text=True, check=True)
    full_ayah_dur = float(probe.stdout.strip() or "6.0")

    processed_ayah_wav = f"ayah_proc_{index}.wav"
    if trim_part == "first_half":
        half_t = round(full_ayah_dur * 0.52, 2)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ayah_mp3, "-t", str(half_t),
            "-af", f"afade=t=out:st={max(half_t - 0.3, 0.2)}:d=0.3",
            "-ar", "44100", "-ac", "2", processed_ayah_wav
        ], check=True)
        ayah_dur = half_t
    elif trim_part == "second_half":
        start_t = round(full_ayah_dur * 0.48, 2)
        rem_t = round(full_ayah_dur - start_t, 2)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start_t), "-i", raw_ayah_mp3,
            "-af", "afade=t=in:d=0.25",
            "-ar", "44100", "-ac", "2", processed_ayah_wav
        ], check=True)
        ayah_dur = rem_t
    else:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ayah_mp3, "-ar", "44100", "-ac", "2", processed_ayah_wav
        ], check=True)
        ayah_dur = full_ayah_dur

    # ضمان أن مدة المشهد بين 6.2 و 8.5 ثانية بحيث يكون مجموع الـ 10 مشاهد ~68 إلى 75 ثانية (أكثر من دقيقة وأقل من 90 ثانية!)
    final_dur = min(max(round(ayah_dur + 0.8, 2), min_dur), 8.6)

    sfx_ogg = f"raw_sfx_{index}.ogg"
    sfx_url, sfx_vol = NATURE_FOLEY_URLS.get(sfx_type, NATURE_FOLEY_URLS["sea_waves"])
    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            # إضافة صدى مسجدي خفيف وفخم (acathedral/aecho) للتلاوة مع صوت الطبيعة الهادئ
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-stream_loop", "2", "-i", sfx_ogg,
                "-i", processed_ayah_wav,
                "-filter_complex",
                f"[1:a]atrim=0:{final_dur},afade=t=in:d=0.3,afade=t=out:st={max(final_dur - 0.5, 0.5)}:d=0.5,volume={sfx_vol}[sfx];"
                f"[2:a]adelay=250|250,aecho=0.8:0.88:45:0.18,volume=1.40[q];"
                f"[0:a][sfx][q]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return final_dur
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", processed_ayah_wav,
        "-filter_complex",
        "[1:a]adelay=250|250,aecho=0.8:0.88:45:0.18,volume=1.40[q];[0:a][q]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)
    return final_dur


def find_uploaded_image_for_scene(scene_number_1based):
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


def render_quran_subtitle_png(ayah_phrase, png_path):
    """رسم الآية القرآنية الكريمة بخط عربي سليم 100% (مع حل مشكلة لفظ الجلالة الله بدون أي مربع ناقص)"""
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_file, 52, layout_engine=ImageFont.Layout.BASIC)
        reshaped = ARABIC_RESHAPER.reshape(ayah_phrase)
        display_text = get_display(reshaped)
    except Exception:
        font = ImageFont.truetype(font_file, 52)
        display_text = ayah_phrase

    bbox = draw.textbbox((0, 0), display_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (1080 - w) // 2
    y_pos = 1530

    pad_x, pad_y = 34, 16
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=24,
        fill=(8, 8, 12, 185),
        outline=(212, 175, 55, 200),
        width=2
    )
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255))
    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 248, 220, 255))
    img.save(png_path, "PNG")


def create_scene_assets(index, scene):
    image_prompt = scene["image_prompt"]
    motion_prompt = scene["motion_prompt"]
    subtitle_text = (scene.get("subtitle_text") or "").strip()

    audio_file = f"scene_{index}.wav"
    duration = create_scene_quran_audio(index, scene, audio_file)

    img_file = f"scene_{index}.jpg"
    obtain_scene_image(index, image_prompt, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 10

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
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

    clean_words = subtitle_text.split()
    phrases = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)] or [subtitle_text]
    step_dur = duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"
    for p_idx, phrase in enumerate(phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_quran_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-i", png_file])
        start_t = round(p_idx * step_dur, 2)
        end_t = round((p_idx + 1) * step_dur, 2)
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(f"{last_stream}[{inp_idx}:v]overlay=0:0:enable='between(t,{start_t},{end_t})'{next_stream}")
        last_stream = next_stream

    filter_parts.append(f"{last_stream}format=yuv420p[vout]")
    # تحديد المدة الصارمة (-t str(duration)) قبل ملف الخرج حتى يظل إجمالي الفيديو ~68 ثانية (> دقيقة و < 90 ثانية لإنستجرام!)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        video_file
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
            "title": f"{title[:80]} ✨ #قرآن #تلاوة #قصص_القرآن",
            "description": f"{title}\n\n#قرآن_كريم #تلاوة_خاشعة #قصص_القرآن #موسى_عليه_السلام #shorts",
            "tags": ["قرآن", "تلاوة خاشعة", "ياسر الدوسري", "قصص القرآن", "موسى عليه السلام", "shorts"],
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
            "description": f"{title} ✨\n\n#قرآن_كريم #تلاوة_خاشعة #قصص_القرآن #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def get_public_video_url(video_path):
    # 1. Catbox Litterbox
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

    # 2. Tmpfiles Direct Link
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": f},
                timeout=180
            ).json()
        if r.get("status") == "success":
            return r["data"]["url"].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception:
        pass

    # 3. Uguu.se Direct Link
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
    caption = f"{title} ✨\n\n#قرآن_كريم #تلاوة_خاشعة #قصص_القرآن #reels"
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
    story = get_quran_simulation_storyboard(QURAN_STORY)
    print(f"📖 عنوان الفيديو: {story['title']}", flush=True)

    scene_videos = []
    total_duration = 0.0
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري تجهيز وتحريك المشهد القرآني {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip, dur = create_scene_assets(idx, scene)
        scene_videos.append(clip)
        total_duration += dur

    print(f"⏱️ إجمالي مدة الفيديو النهائية: {round(total_duration, 1)} ثانية ({round(total_duration / 60, 2)} دقيقة)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري المونتاج النهائي للتلاوة والمحاكاة البصرية...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    # ضبط إجمالي الفيديو بحيث لا يتخطى 86 ثانية أبداً ليقبله إنستجرام ريلز 100% مع بقائه فوق الـ 60 ثانية لتحقيق الأرباح!
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-t", "86",
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
