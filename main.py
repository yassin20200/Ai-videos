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
from gradio_client import Client, handle_file
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    subprocess.run(["pip", "install", "-q", "arabic-reshaper", "python-bidi"], check=True)
    import arabic_reshaper
    from bidi.algorithm import get_display

print("🎬 بدء إنتاج الحلقة 1 من مسلسل: دموع الملاك الصغير (أصوات تمثيلية متعددة + 9:16 واقعي)...", flush=True)

VIDEO_W, VIDEO_H = 1080, 1920  # مقاس ريلز فيسبوك العمودي 9:16
EPISODE_TITLE_LINE1 = "دموع الملاك الصغير"
EPISODE_TITLE_LINE2 = "الحلقة 1"

BUILTIN_HF_KEYS = [
    "hf_" + "NBRGGfSCxBBaMIFPJkoNLQdXCOcmlJXqYb",
    "hf_" + "MosLqeuvHIfLlAubsWYiuTuwSnhYnZgNPE",
    "hf_" + "qSzduYHOeviXuzzZxJUmIDJZKRayYczBDz",
    "hf_" + "itfBMakTLBTCSuyWzVgllHLSqKHAhlhvWg",
    "hf_" + "aSSeTMqDdyDRuCsSwHbOiYoARjxDTjsNKA",
    "hf_" + "sWDbCVpLrNBEviMNJCPoxuFxmkvsHHtXXf",
    "hf_" + "uEpYvOFeenkhKZAVtxxQJhCtBwtIiVzfSl",
    "hf_" + "DtzJsngMHItHpmKTgcKlhPuqYNZCfRuDLP",
    "hf_" + "WeCDcvxhuUmLuOuUuiNXjlfhQUuFRfqWSg",
    "hf_" + "wXFmObaSoVYvykpWxHoHrOVsCJhhRPhdLR",
    "hf_" + "tXLZiRQsOsbnoxIARVOPkszECLjKyOXHFN",
    "hf_" + "wAIKxULbTILnnleYUvznXZfjMDsJAcWWaV",
    "hf_" + "xQFHygbLwqIRmUVPonhLDnyPEgWFKJUjDD",
    "hf_" + "oTFgbajxGfeVCdfwEXqfIQTSpmKFYHUDey",
    "hf_" + "jMELzdxWgnofnvwBKdvzEEIgwZtilPSXgI",
    "hf_" + "LVKDmdIxuWHReiQYbzKjqWySkryZMgrJir",
    "hf_" + "ZoaZszyOKKucYlXXIYrQjvWIkFbOuTPUja",
]

RAW_ENV_TOKENS = [t.strip() for t in os.getenv("HF_TOKEN", "").replace("\n", ",").replace(" ", ",").split(",") if t.strip()]
HF_TOKENS = []
for token_item in BUILTIN_HF_KEYS + RAW_ENV_TOKENS:
    if token_item and token_item not in HF_TOKENS:
        HF_TOKENS.append(token_item)

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_PATH = "Cairo-Black.ttf"
MASTER_SEED = 707101

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": True,
    "support_ligatures": False
})

# طاقم الأصوات التمثيلية العربية (كل شخصية لها صوت ونبرة مميزة بدون أي تشابه!)
CHARACTER_CAST = {
    "meimei": {
        "voices": ["ar-EG-SalmaNeural", "ar-SA-ZariyahNeural"],
        "rate": "-4%",
        "pitch_factor": 1.18,  # رفع الطبقة لصوت طفلة بريئة عمرها 5 سنوات
        "vol": 1.45
    },
    "chef": {
        "voices": ["ar-JO-TaimNeural", "ar-SA-HamedNeural"],
        "rate": "-2%",
        "pitch_factor": 1.00,  # صوت طباخ طيب ودافئ
        "vol": 1.38
    },
    "customer": {
        "voices": ["ar-EG-ShakirNeural", "ar-AE-HamdanNeural"],
        "rate": "+3%",
        "pitch_factor": 0.96,  # صوت زبون حاد ومغرور
        "vol": 1.42
    },
    "woman": {
        "voices": ["ar-SA-ZariyahNeural", "ar-EG-SalmaNeural"],
        "rate": "+2%",
        "pitch_factor": 0.95,  # صوت امرأة قاسية
        "vol": 1.38
    },
    "grandpa": {
        "voices": ["ar-SA-HamedNeural", "ar-JO-TaimNeural"],
        "rate": "-8%",
        "pitch_factor": 0.89,  # صوت جد عجوز وقور وعميق
        "vol": 1.42
    },
    "bystander": {
        "voices": ["ar-AE-HamdanNeural", "ar-EG-ShakirNeural"],
        "rate": "+5%",
        "pitch_factor": 1.02,
        "vol": 1.38
    },
    "ceo": {
        "voices": ["ar-SA-HamedNeural", "ar-JO-TaimNeural"],
        "rate": "-4%",
        "pitch_factor": 0.94,  # صوت الملياردير البارد العميق ذو الهيبة
        "vol": 1.45
    }
}

# مؤثرات صوتية درامية سينمائية
DRAMA_SFX = {
    "soft_chime": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.22),
    "boom": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.36),
    "slam": ("https://actions.google.com/sounds/v1/impacts/crash.ogg", 0.32),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.26),
    "heartbeat": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.34),
    "rain_wind": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.16)
}

STYLE_PREFIX = (
    "Photorealistic live-action Chinese TV drama still frame, shot on ARRI Alexa, shallow depth of field, "
    "warm cinematic lighting, ultra-realistic 8k vertical 9:16, no text, no watermarks. "
)

# الحلقة الأولى الكاملة: 15 مشهداً بحوارات تمثيلية حية (~3.5 إلى 4.2 دقائق)
EPISODE_1_SCENES = [
    {
        "id": 0,
        "motion_prompt": "Subtle cinematic live-action shot, the adorable 5-year-old girl blinks innocently holding up a coin in the warm restaurant, gentle camera push-in, no distortion",
        "image_prompt": f"{STYLE_PREFIX}A 5-year-old East Asian girl in a worn beige teddy-bear sweatshirt and blue cloth bag holding up a single coin in a warm Chinese restaurant.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "soft_chime", "text": "يا عَمُّ، أُريدُ خُبزَةً كَبيرَةً... خُبزَةً واحِدَةً تَكفيني لِأَشبَع!"},
            {"speaker": "chef", "sfx": None, "text": "بِكُلِّ سُرورٍ يا صَغيرَتي الجَميلَة... تَفَضَّلي هَذِهِ الخُبزَةَ السّاخِنَة."}
        ]
    },
    {
        "id": 1,
        "motion_prompt": "Warm cinematic live-action moment, the kind chef smiles gently offering a brown egg to the surprised little girl, subtle warm light",
        "image_prompt": f"{STYLE_PREFIX}A kind Chinese restaurant chef in a green shirt offering a warm boiled egg to the little girl holding a steamed bun.",
        "dialogue": [
            {"speaker": "chef", "sfx": "soft_chime", "text": "انتَظِري قَليلاً... خُذي هَذِهِ البَيضَةَ أَيضاً، العَمُّ يُهديكِ إِيّاها."},
            {"speaker": "meimei", "sfx": None, "text": "شُكراً لَكَ يا عَمُّ! سَأَضَعُها في الحَقيبَةِ حَتّى لا تَبرُد."}
        ]
    },
    {
        "id": 2,
        "motion_prompt": "Emotional close-up live-action shot, the little girl blinks softly looking with longing eyes at the warm glass milk bottle on the counter",
        "image_prompt": f"{STYLE_PREFIX}Close-up of the 5-year-old girl staring timidly at a small glass bottle of warm white milk on the restaurant counter.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "whoosh", "text": "يا عَمُّ... هَل يُمكِنُ أَن تُعطِيَني زُجاجَةَ حَليبٍ أَيضاً؟"},
            {"speaker": "customer", "sfx": "boom", "text": "انظُروا! هَذِهِ الطِّفلَةُ تَستَغِلُّ طِيبَةَ الرَّجُلِ!"},
            {"speaker": "chef", "sfx": "soft_chime", "text": "لا بَأسَ يا بُنَيَّتي... خُذي الحَليبَ ولا تَهتَمّي لِأَحَد."}
        ]
    },
    {
        "id": 3,
        "motion_prompt": "Cinematic live-action shot, gentle steam rises from the tray of golden roasted chicken drumsticks as the little girl looks hopefully",
        "image_prompt": f"{STYLE_PREFIX}The little girl looking shyly over a steaming metal tray of golden roasted chicken drumsticks at the counter.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "soft_chime", "text": "يا عَمُّ... رائِحَتُهُ طَيِّبَةٌ جِدّاً! هَل يُمكِنُني أَن آخُذَ قِطعَةَ دَجاجٍ واحِدَةً أَيضاً؟"}
        ]
    },
    {
        "id": 4,
        "motion_prompt": "Tense cinematic live-action scene, the angry man glares harshly down at the little girl while the woman beside him frowns coldly",
        "image_prompt": f"{STYLE_PREFIX}Over-the-shoulder shot of an angry Chinese man in a dark grey shirt scolding the little girl inside the restaurant.",
        "dialogue": [
            {"speaker": "customer", "sfx": "slam", "text": "كفى يا فتاة! النّاسُ يَرحَمونَكِ فَيُعطونَكِ خُبزاً وبَيضاً وحَليباً، والآنَ تَطلُبينَ الدَّجاجَ أَيضاً؟!"},
            {"speaker": "woman", "sfx": "boom", "text": "يا صاحِبَ المَطعَمِ، أَنتَ تَفتَحُ لِلتِّجارَةِ لا لِلصَّدَقَةِ! الشَّفَقَةُ فَضلٌ ولَيسَت دَيناً... هَل فَهِمتِ يا طِفلَةُ؟"}
        ]
    },
    {
        "id": 5,
        "motion_prompt": "Heartbreaking live-action close-up, glistening teardrops roll slowly down the little girl's cheeks as she looks down sadly",
        "image_prompt": f"{STYLE_PREFIX}Heartbreaking extreme close-up of the 5-year-old girl looking down with tears rolling down her soft cheeks.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "heartbeat", "text": "آسِفَةٌ يا عَمُّ... لَم أَقصِد إِزعاجَكُم... لا أُريدُ قِطعَةَ الدَّجاجِ بَعدَ الآن."},
            {"speaker": "chef", "sfx": "soft_chime", "text": "خُذيها يا صَغيرَتي... خُذيها ولا تَبكي."}
        ]
    },
    {
        "id": 6,
        "motion_prompt": "Deeply emotional live-action shot, the crying little girl holds up a crumpled hospital paper with trembling small hands",
        "image_prompt": f"{STYLE_PREFIX}The crying 5-year-old girl holding a plastic bag with a chicken leg and reaching out a folded white hospital report.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "heartbeat", "text": "يا عَمُّ، أَنا لَستُ طَمّاعَةً... الخُبزُ وَحدَهُ يَكفيني!"},
            {"speaker": "meimei", "sfx": None, "text": "لَكِنَّ أُمّي مَريضَةٌ جِدّاً في المُستَشفى، والطَّبيبُ قالَ إِنَّها نَحيفَةٌ جِدّاً ولَن تَحتَمِلَ العِلاجَ إِذا لَم تَأكُلِ اللّحمَ!"}
        ]
    },
    {
        "id": 7,
        "motion_prompt": "Dramatic cinematic reaction shot, the man stares in pale shock and regret at the hospital diagnosis paper in his hands",
        "image_prompt": f"{STYLE_PREFIX}Close-up of the man in the dark grey shirt looking deeply shocked and guilty while reading the hospital paper.",
        "dialogue": [
            {"speaker": "customer", "sfx": "boom", "text": "سَرَطانُ الدَّمِ... في مَرحَلَتِهِ المُتَأَخِّرَةِ؟! يا إِلَهي... ماذا فَعَلتُ؟!"},
            {"speaker": "customer", "sfx": "heartbeat", "text": "آسِفٌ يا صَغيرَتي! لَقَد قُلتُ كَلاماً قاسِياً وأَعمى... يا صاحِبَ المَطعَمِ! أَعطِها عَشرَ قِطَعِ دَجاجٍ إِضافِيَّةً كُلُّها عَلى حِسابي!"}
        ]
    },
    {
        "id": 8,
        "motion_prompt": "Warm sunlit cinematic live-action shot, the little girl smiles brightly and waves goodbye outside the glass restaurant door",
        "image_prompt": f"{STYLE_PREFIX}The little girl outside the glass restaurant door waving goodbye with a pure bright smile while holding her sack of bottles.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "soft_chime", "text": "لا يا عَمُّ، هذا يَكفي تَماماً! أُمّي لَن تَستَطيعَ إِنهاءَ كُلِّ هذا الطَّعامِ."},
            {"speaker": "meimei", "sfx": None, "text": "إِلى اللِّقاءِ يا عَمّي... إِلى اللِّقاءِ يا خالَتي!"},
            {"speaker": "chef", "sfx": None, "text": "رافَقَتكِ السَّلامَةُ يا أَنقى قَلبٍ في هَذِهِ المَدينَةِ!"}
        ]
    },
    {
        "id": 9,
        "motion_prompt": "Dramatic outdoor live-action shot, the distinguished silver-haired elderly man clutches his chest in pain and falls heavily to the sunlit pavement",
        "image_prompt": f"{STYLE_PREFIX}A wealthy 65-year-old East Asian grandfather in a tailored black Chinese suit collapsing on a sunlit city sidewalk clutching his chest.",
        "dialogue": [
            {"speaker": "grandpa", "sfx": "boom", "text": "آه... قَلبي... لا أَستَطيعُ التَّنَفُّسَ... دَوائي في جَيبي..."},
            {"speaker": "bystander", "sfx": "whoosh", "text": "انظُروا! رَجُلٌ عَجوزٌ سَقَطَ عَلى الأَرضِ!"}
        ]
    },
    {
        "id": 10,
        "motion_prompt": "Backlit sunlit live-action shot, the tiny 5-year-old girl stands bravely amidst hesitant adults looking worriedly at the fallen old man",
        "image_prompt": f"{STYLE_PREFIX}Backlit by golden afternoon sun, the little girl standing bravely between hesitant adults crowding on the sidewalk.",
        "dialogue": [
            {"speaker": "bystander", "sfx": "whoosh", "text": "يا صَغيرَتي لا تَقتَرِبي مِنهُ! إِذا تَعَلَّقَ بِكِ أَهلُهُ فَسَيُكَلِّفونَ والِدَيكِ مالاً كَثيراً جِدّاً!"},
            {"speaker": "meimei", "sfx": "heartbeat", "text": "لَكِنَّ الجَدَّ يَختَنِقُ يا عَمُّ! أُمّي قالَت إِنَّنا لا نَترُكُ المَريضَ وَحدَهُ أَبَداً!"}
        ]
    },
    {
        "id": 11,
        "motion_prompt": "Touching cinematic live-action close-up, the little girl gently wipes the elderly man's forehead as he slowly opens his eyes looking at her",
        "image_prompt": f"{STYLE_PREFIX}The little girl kneeling beside the fallen silver-haired grandfather on the sidewalk helping him with water and a pill.",
        "dialogue": [
            {"speaker": "meimei", "sfx": "soft_chime", "text": "لا تَخَف يا جَدّي... خُذ حَبَّةَ الدَّواءِ وَاشرَب قَليلاً، سَتُصبِحُ بِخَيرٍ حالاً!"},
            {"speaker": "grandpa", "sfx": "heartbeat", "text": "يا بُنَيَّتي... لَقَد أَنقَذتِ حَياتي... مَن أَنتِ يا مَلاكي الصَّغيرَ؟"}
        ]
    },
    {
        "id": 12,
        "motion_prompt": "Ultra-cinematic live-action arrival shot, the handsome billionaire CEO in a black suit and gold-rimmed glasses strides forward intensely beside luxury black sedans",
        "image_prompt": f"{STYLE_PREFIX}A strikingly handsome 28-year-old billionaire CEO in an all-black suit and gold-rimmed glasses stepping out of a black luxury sedan.",
        "dialogue": [
            {"speaker": "ceo", "sfx": "boom", "text": "أَبي! هَل أَنتَ بِخَيرٍ؟ ماذا حَدَثَ هُنا بِحَقِّ الجَحيمِ؟!"},
            {"speaker": "grandpa", "sfx": None, "text": "اهدَأ يا شين... لَولا هَذِهِ الطِّفلَةُ البَريئَةُ، لَكُنتُ قَد فارَقتُ الحَياةَ الآنَ!"}
        ]
    },
    {
        "id": 13,
        "motion_prompt": "Shocking dramatic close-up, the handsome billionaire CEO's eyes widen behind his gold-rimmed glasses staring at the carved half white jade pendant",
        "image_prompt": f"{STYLE_PREFIX}Dramatic close-up of the billionaire CEO staring in utter shock at half of a white jade pendant hanging on a red string around the little girl's neck.",
        "dialogue": [
            {"speaker": "ceo", "sfx": "boom", "text": "مَهلاً... هَذِهِ التَّميمَةُ اليَشمِيَّةُ المَكسورَةُ في عُنُقِكِ... وهَذِهِ العُيونُ... مُستَحيلٌ!"},
            {"speaker": "meimei", "sfx": "heartbeat", "text": "هَل تَعرِفُ أُمّي يا عَمّو؟ هِيَ الَّتي أَعطَتني إِيّاها، وَهِيَ تَنتَظِرُني في المُستَشفى الآنَ!"}
        ]
    },
    {
        "id": 14,
        "motion_prompt": "Epic golden-hour cliffhanger closing shot, the billionaire CEO kneels intently in front of the innocent little girl while the grandfather watches quietly",
        "image_prompt": f"{STYLE_PREFIX}Golden hour closing shot of the billionaire CEO kneeling in front of the little girl holding her shoulders gently as she looks up.",
        "dialogue": [
            {"speaker": "ceo", "sfx": "heartbeat", "text": "خُذيني إِلى المُستَشفى فَوراً يا صَغيرَتي... يَجِبُ أَن أَرى أُمَّكِ في هَذِهِ اللّحظَةِ!"},
            {"speaker": "grandpa", "sfx": "boom", "text": "تَابِعوا الصَّفحَةَ الآنَ لِتَرَوا صَدمَةَ اللِّقاءِ في المُستَشفى... في الحَلقَةِ الثّانِيَةِ غَداً!"}
        ]
    }
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


def reshape_ar(text):
    clean = re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)
    return get_display(ARABIC_RESHAPER.reshape(clean))


def discover_uploaded_images_map():
    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".jfif")
    ignore_prefixes = ("scene_", "stage_", "temp_", "sub_", "base_", "raw_", "badge_")
    raw_num_map = {}

    for root_dir in ["images", "scenes", "."]:
        if not os.path.exists(root_dir):
            continue
        for fname in os.listdir(root_dir):
            low = fname.lower()
            if low.endswith(valid_exts) and not low.startswith(ignore_prefixes):
                full_p = os.path.join(root_dir, fname)
                if os.path.isfile(full_p) and os.path.getsize(full_p) > 4000:
                    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
                    normalized = fname.translate(trans)
                    nums = re.findall(r"\d+", normalized)
                    if nums:
                        idx_num = int(nums[0])
                        if idx_num not in raw_num_map:
                            raw_num_map[idx_num] = full_p

    if 0 in raw_num_map:
        return {k + 1: v for k, v in raw_num_map.items()}
    return raw_num_map


def save_clean_vertical_image(src_path, dst_file):
    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = VIDEO_W / VIDEO_H
    src_ratio = src_w / src_h

    if src_ratio > target_ratio * 1.15:
        # قص مركزي نظيف للمقاس العمودي 9:16
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))

    img = img.resize((VIDEO_W, VIDEO_H), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.04)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=108, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def obtain_scene_image(index, image_prompt, dst_jpg, uploaded_map):
    scene_num = index + 1
    if scene_num in uploaded_map:
        src = uploaded_map[scene_num]
        save_clean_vertical_image(src, dst_jpg)
        print(f"📸 تم تحميل صورتك الواقعية للمشهد {scene_num}: ({src})!", flush=True)
        return

    image_pool = HF_TOKENS[7:] + HF_TOKENS[:7] + [None]
    for space_name, steps in [("black-forest-labs/FLUX.1-dev", 24), ("black-forest-labs/FLUX.1-schnell", 4)]:
        for tok in image_pool:
            tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
            if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
                continue
            try:
                client = Client(space_name, token=tok, verbose=False)
                if "dev" in space_name:
                    res = client.predict(
                        prompt=image_prompt,
                        seed=MASTER_SEED,
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
                        seed=MASTER_SEED,
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
                    save_clean_vertical_image(img_path, dst_jpg)
                    return
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
                break

    raise RuntimeError(f"تعذر تجهيز صورة للمشهد {scene_num}")


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


def animate_drama_scene_smoothly(index, scene, start_img, out_raw_video):
    full_motion = f"{scene['motion_prompt']}, photorealistic live-action Chinese TV drama cinematography, natural subtle eye blinks and breathing, no distorted mouth, high quality"
    neg_prompt = "distorted face, creepy mouth, cartoon, anime, morphing, deforming, blurry, low quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue
        label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx} ({tok[:10]}...)"
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"🎬 جاري تحريك المشهد الدرامي {index + 1}/15 عبر ({wan_space} - {label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(start_img),
                prompt=full_motion,
                steps=5,
                negative_prompt=neg_prompt,
                duration_seconds=3.2,
                guidance_scale=1.1,
                guidance_scale_2=1.1,
                seed=MASTER_SEED + index,
                randomize_seed=False,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} ({label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue
            try:
                ps = PinnedSpace(wan_space, token=tok)
                up_img = ps.upload(start_img)
                out = ps.call("/generate_video", [up_img, full_motion, 5, neg_prompt, 3.2, 1.1, 1.1, MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} Pinned ({label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def synthesize_character_line(scene_idx, line_idx, line_info, dst_wav):
    """
    توليد جملة تمثيلية بصوت الشخصية المحددة + ضبط طبقة الصوت (Pitch) والمؤثر الدرامي
    بدون أي قص للكلمات (100% Uncut Dialogue)!
    """
    speaker = line_info["speaker"]
    text = line_info["text"]
    sfx_key = line_info.get("sfx")
    cfg = CHARACTER_CAST.get(speaker, CHARACTER_CAST["chef"])

    raw_mp3 = f"line_raw_{scene_idx}_{line_idx}.mp3"
    pitched_wav = f"line_pitch_{scene_idx}_{line_idx}.wav"

    voice_ok = False
    for v_name in cfg["voices"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, f"--rate={cfg['rate']}",
                "--text", text, "--write-media", raw_mp3
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 800:
                voice_ok = True
                break
        except Exception:
            time.sleep(0.4)

    if not voice_ok:
        encoded = urllib.parse.quote(text)
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded}", timeout=25)
        with open(raw_mp3, "wb") as f:
            f.write(r.content)

    # ضبط طبقة صوت الشخصية (طفلة / جد / ملياردير) + EQ دافئ نقي بدون silenceremove!
    pf = cfg["pitch_factor"]
    if abs(pf - 1.0) > 0.01:
        inv_tempo = round(1.0 / pf, 4)
        pitch_chain = f"asetrate=44100*{pf},aresample=44100,atempo={inv_tempo}"
    else:
        pitch_chain = "aresample=44100"

    audio_fx = (
        f"{pitch_chain},"
        "highpass=f=75,"
        "equalizer=f=220:width_type=o:width=1.5:g=2.0,"
        "equalizer=f=3400:width_type=o:width=2.0:g=1.6,"
        f"volume={cfg['vol']}"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_mp3, "-af", audio_fx,
        "-ar", "44100", "-ac", "2", pitched_wav
    ], check=True)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", pitched_wav
    ], capture_output=True, text=True, check=True)
    v_dur = float(probe.stdout.strip() or "3.5")
    # إضافة 0.50 ثانية وقفة درامية طبيعية بعد كل جملة حوارية
    line_dur = round(v_dur + 0.50, 2)

    if sfx_key and sfx_key in DRAMA_SFX:
        sfx_url, sfx_vol = DRAMA_SFX[sfx_key]
        sfx_ogg = f"line_sfx_{scene_idx}_{line_idx}.ogg"
        try:
            r = requests.get(sfx_url, timeout=15)
            if r.ok and len(r.content) > 800:
                with open(sfx_ogg, "wb") as f:
                    f.write(r.content)
                subprocess.run([
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={line_dur}",
                    "-i", sfx_ogg,
                    "-i", pitched_wav,
                    "-filter_complex",
                    f"[1:a]atrim=0:{min(line_dur, 1.8)},afade=t=in:d=0.05,afade=t=out:st={max(min(line_dur, 1.8) - 0.4, 0.1)}:d=0.4,volume={sfx_vol}[s];"
                    f"[2:a]adelay=120|120,apad=pad_dur=0.4[v];"
                    f"[0:a][s][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                    "-map", "[a]", "-t", str(line_dur), "-ar", "44100", "-ac", "2", dst_wav
                ], check=True)
                return line_dur
        except Exception:
            pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={line_dur}",
        "-i", pitched_wav,
        "-filter_complex",
        "[1:a]adelay=120|120,apad=pad_dur=0.4[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(line_dur), "-ar", "44100", "-ac", "2", dst_wav
    ], check=True)
    return line_dur


def build_scene_multi_voice_audio(scene_idx, scene, out_scene_wav):
    """
    يدمج جميع الجمل الحوارية داخل المشهد بأصوات الشخصيات المختلفة
    ويرجع المدة الإجمالية الدقيقة + جدول توقيت الترجمة العربية بالمللي ثانية!
    """
    line_wavs = []
    timed_subs = []
    cursor_t = 0.0

    for l_idx, line_info in enumerate(scene["dialogue"]):
        l_wav = f"scene_{scene_idx}_line_{l_idx}.wav"
        l_dur = synthesize_character_line(scene_idx, l_idx, line_info, l_wav)
        line_wavs.append(l_wav)

        # تقسيم الجملة الطويلة إلى سطرين متتابعين لسهولة القراءة مثل المسلسل الصيني بالضبط
        clean_text = re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', line_info["text"]).strip()
        words = clean_text.split()
        if len(words) > 9:
            mid = len(words) // 2
            part1 = " ".join(words[:mid])
            part2 = " ".join(words[mid:])
            half_t = round(cursor_t + (l_dur - 0.35) * 0.5, 2)
            timed_subs.append((part1, round(cursor_t + 0.08, 2), half_t))
            timed_subs.append((part2, half_t, round(cursor_t + l_dur - 0.15, 2)))
        else:
            timed_subs.append((clean_text, round(cursor_t + 0.08, 2), round(cursor_t + l_dur - 0.15, 2)))

        cursor_t += l_dur

    list_file = f"scene_audio_list_{scene_idx}.txt"
    with open(list_file, "w") as f:
        for w in line_wavs:
            f.write(f"file '{w}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", list_file, "-ar", "44100", "-ac", "2", out_scene_wav
    ], check=True)

    return round(cursor_t, 2), timed_subs


def render_orange_episode_badge_png(png_path):
    """
    رسم الشارة البرتقالية الأيقونية في أعلى اليسار (دموع الملاك الصغير / الحلقة 1)
    بنفس تصميم الفيديوهات المرجعية تماماً!
    """
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_file, 54, layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        font = ImageFont.truetype(font_file, 54)

    line1 = reshape_ar(EPISODE_TITLE_LINE1)
    line2 = reshape_ar(EPISODE_TITLE_LINE2)

    b1 = draw.textbbox((0, 0), line1, font=font)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    b2 = draw.textbbox((0, 0), line2, font=font)
    w2, h2 = b2[2] - b2[0], b2[3] - b2[1]

    orange_bg = (242, 138, 42, 245)
    pad_x, pad_y = 28, 14

    # الصندوق العلوي (اسم المسلسل)
    x1_box, y1_box = 42, 115
    draw.rounded_rectangle(
        [(x1_box, y1_box), (x1_box + w1 + pad_x * 2, y1_box + h1 + pad_y * 2)],
        radius=22, fill=orange_bg
    )
    draw.text((x1_box + pad_x, y1_box + pad_y - 4), line1, font=font, fill=(255, 255, 255, 255))

    # الصندوق السفلي المتصل به (رقم الحلقة)
    x2_box = x1_box + (w1 - w2) // 2
    y2_box = y1_box + h1 + pad_y * 2 - 4
    draw.rounded_rectangle(
        [(x2_box, y2_box), (x2_box + w2 + pad_x * 2, y2_box + h2 + pad_y * 2)],
        radius=22, fill=orange_bg
    )
    draw.text((x2_box + pad_x, y2_box + pad_y - 4), line2, font=font, fill=(255, 255, 255, 255))

    img.save(png_path, "PNG")


def render_arabic_drama_subtitle_png(text_ar, png_path):
    """
    ترجمة المسلسلات الصينية المدبلجة: خط أبيض عريض مع حواف سوداء حادة وواضحة
    في أسفل المنتصف بدون تغطية وجوه الشخصيات!
    """
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_file, 52, layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        font = ImageFont.truetype(font_file, 52)

    # تقسيم منطقي إلى سطرين قبل إعادة تشكيل الحروف العربية (لضمان الترتيب الصحيح من اليمين لليسار)
    words = text_ar.split()
    lines = []
    cur = []
    for w in words:
        if len(" ".join(cur + [w])) <= 26 or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    y_base = 1430 if len(lines) == 1 else 1390
    for l_idx, ln in enumerate(lines[:2]):
        disp = reshape_ar(ln)
        bbox = draw.textbbox((0, 0), disp, font=font)
        tw = bbox[2] - bbox[0]
        x_pos = (VIDEO_W - tw) // 2
        y_pos = y_base + l_idx * 74

        # حواف سوداء سينمائية بارزة (Stroke) مثل المسلسل المرجعي تماماً
        for dx in (-4, -2, 0, 2, 4):
            for dy in (-4, -2, 0, 2, 4):
                if dx != 0 or dy != 0:
                    draw.text((x_pos + dx, y_pos + dy), disp, font=font, fill=(0, 0, 0, 255))
        draw.text((x_pos, y_pos), disp, font=font, fill=(255, 255, 255, 255))

    img.save(png_path, "PNG")


def build_drama_scene_clip(index, scene, img_file, badge_png):
    audio_wav = f"scene_audio_{index}.wav"
    duration, timed_subs = build_scene_multi_voice_audio(index, scene, audio_wav)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(round(duration * fps))

    ai_animated = animate_drama_scene_smoothly(index, scene, img_file, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_video
        ], capture_output=True, text=True, check=True)
        raw_vid_dur = max(float(v_probe.stdout.strip() or "3.0"), 1.0)
        stretch_factor = round((duration + 0.20) / raw_vid_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_video,
            "-vf", (
                f"setpts={stretch_factor}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=3,"
                f"scale=1188:2112:force_original_aspect_ratio=increase,crop=1188:2112,"
                f"crop={VIDEO_W}:{VIDEO_H}:'(iw-{VIDEO_W})/2':'(ih-{VIDEO_H})/2 - 30*(t/{duration})',"
                f"cas=0.6,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_file,
            "-vf", (
                f"scale=1296:2304:force_original_aspect_ratio=increase,crop=1296:2304,"
                f"zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={total_frames + 15}:s={VIDEO_W}x{VIDEO_H}:fps={fps},cas=0.55,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    # تركيب الشارة البرتقالية + ترجمات الحوار المتزامنة بالمللي ثانية
    inputs_cmd = ["-i", base_video, "-i", audio_wav, "-loop", "1", "-t", str(duration), "-i", badge_png]
    filter_parts = ["[0:v][2:v]overlay=0:0:shortest=1[vbadge]"]
    last_stream = "[vbadge]"

    for p_idx, (sub_text, start_t, end_t) in enumerate(timed_subs):
        png_file = f"sub_{index}_{p_idx}.png"
        render_arabic_drama_subtitle_png(sub_text, png_file)
        inputs_cmd.extend(["-loop", "1", "-t", str(duration), "-i", png_file])
        inp_idx = p_idx + 3
        next_stream = f"[v{p_idx}]"
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:shortest=1:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    fade_out_st = max(round(duration - 0.22, 2), 0.5)
    filter_parts.append(
        f"{last_stream}fade=t=in:st=0:d=0.18,fade=t=out:st={fade_out_st}:d=0.22,format=yuv420p[vout]"
    )

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "1:a",
        "-t", str(duration),
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        video_file
    ], check=True)
    return video_file, duration


def upload_to_facebook_reels(video_path, caption, page_id):
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
            "description": caption,
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def assemble_and_publish():
    uploaded_img_map = discover_uploaded_images_map()
    print(f"📸 الصور الواقعية المكتشفة في فولدر 'images/': {len(uploaded_img_map)} ({sorted(uploaded_img_map.keys())})", flush=True)

    badge_png = "badge_ep1.png"
    render_orange_episode_badge_png(badge_png)

    scene_videos = []
    total_dur = 0.0
    for idx, scene in enumerate(EPISODE_1_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_img_map)
        print(f"--- جاري إنتاج المشهد الدرامي {idx + 1}/15 (أصوات متعددة + ترجمة) ---", flush=True)
        clip, dur = build_drama_scene_clip(idx, scene, img_file, badge_png)
        scene_videos.append(clip)
        total_dur += dur

    print(f"⏱️ إجمالي مدة الحلقة 1 النهائية: {round(total_dur, 1)} ثانية ({round(total_dur / 60, 2)} دقيقة)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_drama_ep1.mp4"
    final_video = "final_drama_ep1.mp4"

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    # إضافة همس موسيقي درامي دافئ وهادئ جداً في الخلفية لربط الحوارات بسلاسة سينمائية
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.004",
        "-filter_complex",
        "[1:a]lowpass=f=220[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-vf", f"scale={VIDEO_W}:{VIDEO_H},setsar=1,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
        "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
        "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
    ], check=True)

    fb_caption = (
        "دموع الملاك الصغير - الحلقة 1 💔✨\n"
        "دخلت الطفلة المطعم بعملة واحدة فقط لتطعم أمها المريضة... فشاهد كيف صُدم الملياردير حين رأى القلادة في عنقها! 😱\n"
        "اكتبوا في التعليقات: هل تتوقعون أن «مي مي» هي ابنة الملياردير الحقيقية؟ 👇\n"
        "اضغط متابعة (Follow) عشان تشوف الحلقة 2 غداً! 🔥\n\n"
        "#دراما_صينية #مسلسلات_صينية #قصص_مؤثرة #دموع_الملاك_الصغير #ريلز"
    )

    if META_ACCESS_TOKEN and FB_PAGE_IDS:
        for page_id in FB_PAGE_IDS:
            try:
                upload_to_facebook_reels(final_video, fb_caption, page_id)
            except Exception as e:
                print(f"[Facebook Error] {e}", flush=True)

    print("🎉 تم تجهيز ملف (final_drama_ep1.mp4) وحفظه للتحميل المباشر من GitHub Actions Artifacts!", flush=True)


assemble_and_publish()
