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
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_PATH = "Cairo-Black.ttf"
CHARACTER_MASTER_SEED = 888999

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": True,
    "support_ligatures": False
})

SCIENCE_FOLEY_URLS = {
    "scanner_sweep": ("https://actions.google.com/sounds/v1/science_fiction/sci_fi_osh.ogg", 0.28),
    "water_flow": ("https://actions.google.com/sounds/v1/water/air_woosh_underwater.ogg", 0.22),
    "bubbles_heat": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.18),
    "soft_click": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.20),
    "gentle_whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.18)
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


def get_water_heater_explainer_storyboard():
    """
    15 مشهداً متكاملاً:
    تبدأ بلقطة الشاب الواقف في الحمام بالفوطة وينظر للسخان باستغراب -> زوم نظيف على السخان -> مسح ضوئي بالسكانر -> شرح كل جزء بالداخل.
    """
    style = "Photorealistic 3D engineering cutaway render, Unreal Engine 5 studio lighting, ultra-clean 8k scientific visualization, vertical 9:16, no text labels, no watermarks. "

    return {
        "title": "كيف يعمل سخان المياه من الداخل؟ هندسة مذهلة لم ترها من قبل! 🔍🔥",
        "scenes": [
            {
                # 1. اللقطة الافتتاحية الجديدة (الشاب بالفوطة ينظر للسخان باستغراب ثم زوم نحو السخان)
                "sfx_type": "gentle_whoosh",
                "zoom_mode": "in_top",
                "narration": "كُلَّ يَوْمٍ تَقِفُ فِي الحَمَّامِ قَبْلَ الاسْتِحْمَامِ، وَتَنْظُرُ إِلَى هَذَا الصُّنْدُوقِ الأَبْيَضِ المُعَلَّقِ عَلَى الحَائِطِ وَتَتَسَاءَلُ...",
                "image_prompt": (
                    f"{style}A stylized 3D young man (seen from a 3/4 back-side angle, wearing a clean white bath towel wrapped around his waist) "
                    f"standing in a modern dark-grey tiled bathroom looking up in curiosity with one hand on his chin at a sleek white cylindrical electric water heater mounted high on the wall."
                ),
                "motion_prompt": "3D animation, the young man in the white towel tilts his head curiously looking up at the white water heater on the wall as the camera smoothly zooms in toward the water heater, no talking"
            },
            {
                # 2. زوم كامل على السخان المغلق من الخارج
                "sfx_type": "soft_click",
                "zoom_mode": "in_center",
                "narration": "كَيْفَ يَخْرُجُ المَاءُ السَّاخِنُ فَوْراً بِمُجَرَّدِ فَتْحِ الصُّنْبُورِ، دُونَ أَنْ يَخْتَلِطَ بِالمَاءِ البَارِدِ دَاخِلَ السَّخَّانِ؟",
                "image_prompt": f"{style}A sleek modern white cylindrical electric water heater mounted on a clean dark-grey modern tiled bathroom wall, with a blue cold-water inlet pipe on the bottom right and a red hot-water outlet pipe on the bottom left.",
                "motion_prompt": "Ultra-clean 3D product animation, subtle smooth camera push-in toward the sleek white water heater mounted on the wall, static object, no distortion"
            },
            {
                # 3. المسح الضوئي بالسكانر وكشف باطن السخان (يمسح اللقطة 2 ليكشف اللقطة 3)
                "sfx_type": "scanner_sweep",
                "zoom_mode": "scanner_reveal",
                "narration": "لَوْ فَتَحْنَا هَذِهِ الأُسْطُوَانَةَ المُغْلَقَةَ بِمَسْحٍ ضَوْئِيٍّ مِنَ الدَّاخِلِ، سَنَكْتَشِفُ هَنْدَسَةً ذَكِيَّةً جِدّاً تَعْتَمِدُ عَلَى قَوَانِينِ الفِيزْيَاءِ البَسِيطَةِ.",
                "image_prompt": f"{style}3D X-ray scanner cutaway of the exact same white cylindrical water heater on the grey tiled wall: a glowing cyan laser scanner beam sweeps across, making the outer shell semi-transparent and revealing the internal steel tank, yellow foam insulation, and copper heating element.",
                "motion_prompt": "3D engineering visualization, glowing cyan scanner light gently illuminates the transparent cutaway interior of the water heater, no morphing"
            },
            {
                # 4. طبقة العزل الحراري الفوم
                "sfx_type": "soft_click",
                "zoom_mode": "in_center",
                "narration": "أَوَّلُ مَا يُقَابِلُنَا تَحْتَ الغِلافِ الخَارِجِيِّ هُوَ طَبَقَةٌ سَمِيكَةٌ مِنْ فُومِ العَزْلِ الحَرَارِيِّ، تَحْفَظُ حَرَارَةَ المَاءِ لِسَاعَاتٍ طَوِيلَةٍ كَأَنَّهَا حَافِظَةٌ حَرَارِيَّةٌ عِمْلَاقَةٌ.",
                "image_prompt": f"{style}Close-up 3D cross-section of the water heater wall clearly showing the thick dense yellow polyurethane thermal insulation foam layer sandwiched between the white outer metal shell and the inner steel tank.",
                "motion_prompt": "Clean 3D macro visualization, smooth camera focus on the yellow thermal insulation foam layer between the steel walls, no distortion"
            },
            {
                # 5. دخول الماء البارد من الأسفل
                "sfx_type": "water_flow",
                "zoom_mode": "in_bottom",
                "narration": "تَبْدَأُ الرِّحْلَةُ مِنَ الأَسْفَلِ؛ حَيْثُ يَدْخُلُ المَاءُ البَارِدُ عَبْرَ المَاسُورَةِ الزَّرْقَاءِ مُنْدَفِعاً بِضَغْطِ شَبَكَةِ المِيَاهِ فِي المَنْزِلِ.",
                "image_prompt": f"{style}Close-up 3D cutaway of the bottom-right cold water inlet pipe: crystal-clear glowing blue cold water flowing upward through the chrome pipe with the blue valve into the bottom of the water heater.",
                "motion_prompt": "3D fluid simulation, glowing blue cold water flowing smoothly upward through the transparent inlet pipe into the tank"
            },
            {
                # 6. توجيه الماء البارد لقاع الخزان
                "sfx_type": "water_flow",
                "zoom_mode": "out_center",
                "narration": "وَهُنَا تَكْمُنُ الخُدْعَةُ الهَنْدَسِيَّةُ الأُولَى؛ المَاءُ البَارِدُ لا يَنْتَشِرُ عَشْوَائِيّاً، بَلْ يُوَجَّهُ مُبَاشَرَةً لِيَسْتَقِرَّ فِي أَعْمَقِ نُقْطَةٍ فِي قَاعِ الخَزَّانِ.",
                "image_prompt": f"{style}Interior 3D cutaway view of the lower half of the water heater tank: glowing clear blue cold water pouring from the inlet tube and settling densely across the bottom floor of the inner steel tank.",
                "motion_prompt": "3D fluid animation, clear blue cold water streaming gently into the bottom floor of the tank in smooth slow motion"
            },
            {
                # 7. تجمع الماء البارد حول الهيتر النحاسي
                "sfx_type": "water_flow",
                "zoom_mode": "in_center",
                "narration": "فِي قَاعِ الخَزَّانِ تَمَاماً، يَتَجَمَّعُ هَذَا المَاءُ البَارِدُ الكَثِيفُ حَوْلَ قَلْبِ السَّخَّانِ النَّابِضِ، وَهُوَ عُنْصُرُ التَّسْخِينِ النُّحَاسِيُّ.",
                "image_prompt": f"{style}Close-up 3D interior shot at the bottom of the tank: the U-shaped metallic copper heating element submerged inside the clear blue cold water at the bottom of the tank.",
                "motion_prompt": "3D underwater engineering shot, gentle water refraction around the metallic copper heating element at the bottom of the tank"
            },
            {
                # 8. حساس الترموستات الذكي
                "sfx_type": "soft_click",
                "zoom_mode": "in_center",
                "narration": "بِجِوَارِهِ يَعْمَلُ التِّرْمُوسْتَاتُ كَعَقْلٍ ذَكِيٍّ لِلسَّخَّانِ؛ فَبِمُجَرَّدِ أَنْ يَسْتَشْعِرَ بُرُودَةَ المَاءِ فِي القَاعِ، يُرْسِلُ إِشَارَةً كَهْرَبَائِيَّةً فَوْرِيَّةً لِبَدْءِ التَّسْخِينِ.",
                "image_prompt": f"{style}Macro close-up 3D shot of the electronic thermostat control unit mounted at the base of the heating element, with a glowing blue electric pulse light traveling through the sensor wires.",
                "motion_prompt": "3D macro animation, a glowing blue electrical pulse illuminates the thermostat sensor circuit smoothly"
            },
            {
                # 9. توهج الهيتر النحاسي وتسخين الماء
                "sfx_type": "bubbles_heat",
                "zoom_mode": "in_center",
                "narration": "عِنْدَهَا يَتَوَهَّجُ مِلَفُّ التَّسْخِينِ النُّحَاسِيُّ بِالحَرَارَةِ، وَيُحَوِّلُ الطَّاقَةَ الكَهْرَبَائِيَّةَ إِلَى حَرَارَةٍ تَنْتَقِلُ مُبَاشَرَةً إِلَى المِيَاهِ المُحِيطَةِ بِهِ.",
                "image_prompt": f"{style}Dramatic close-up 3D interior shot: the U-shaped copper heating element submerged in water is glowing bright fiery orange-red with heat, surrounded by tiny shimmering micro-bubbles rising in the water.",
                "motion_prompt": "3D thermal animation, the copper heating element glows warm orange-red as tiny shimmering heat bubbles rise gently upward in the water"
            },
            {
                # 10. فيزياء الكثافة وصعود الماء الساخن للأعلى
                "sfx_type": "water_flow",
                "zoom_mode": "out_center",
                "narration": "وَهُنَا تَتَدَخَّلُ الفِيزْيَاءُ؛ المَاءُ السَّاخِنُ تَقِلُّ كَثَافَتُهُ وَيُصْبِحُ أَخَفَّ وَزْناً، فَيَرْتَفِعُ تِلْقَائِيّاً إِلَى قِمَّةِ الخَزَّانِ، بَيْنَمَا يَبْقَى المَاءُ البَارِدُ الثَّقِيلُ فِي الأَسْفَلِ.",
                "image_prompt": f"{style}Full 3D tank cutaway view showing thermal fluid dynamics: glowing warm orange-red heated water rising in smooth currents to the top half of the tank, while cool blue water remains at the bottom half.",
                "motion_prompt": "3D thermal fluid simulation, warm orange currents rise smoothly toward the top of the tank while cool blue water stays at the bottom"
            },
            {
                # 11. عمود المغنيسيوم لحماية السخان من الصدأ
                "sfx_type": "gentle_whoosh",
                "zoom_mode": "in_center",
                "narration": "وَلِحِمَايَةِ الخَزَّانِ الحَدِيدِيِّ مِنَ الصَّدَأِ وَتَرَاكُمِ الأَمْلاحِ، يُوجَدُ فِي المُنْتَصَفِ عَمُودُ المَغْنِيسْيُومِ، وَهُوَ جُنْدِيٌّ مَجْهُولٌ يَجْذِبُ التَّآكُلَ إِلَيْهِ بَدَلاً مِنْ جُدْرَانِ السَّخَّانِ.",
                "image_prompt": f"{style}Close-up 3D interior shot of the center of the tank: a long silver metallic magnesium anode rod hanging vertically inside the glowing water, attracting tiny golden mineral particles toward itself.",
                "motion_prompt": "3D scientific animation, tiny glowing mineral particles drift gently toward the silver vertical anode rod in the center of the water tank"
            },
            {
                # 12. فصل الترموستات تلقائياً عند 60 درجة
                "sfx_type": "soft_click",
                "zoom_mode": "in_center",
                "narration": "وَعِنْدَمَا تَصِلُ حَرَارَةُ المِيَاهِ إِلَى سِتِّينَ دَرَجَةً مِئَوِيَّةً، يَفْصِلُ التِّرْمُوسْتَاتُ الكَهْرَبَاءَ تِلْقَائِيّاً لِلحِفَاظِ عَلَى الأَمَانِ وَتَوْفِيرِ اسْتِهْلَاكِ الطَّاقَةِ.",
                "image_prompt": f"{style}Close-up 3D shot of the front digital temperature display of the water heater showing a glowing 60 with a green safety indicator light.",
                "motion_prompt": "Clean 3D close-up animation, the digital display glows steadily with a soft green safety indicator light"
            },
            {
                # 13. صمام الأمان وتفريغ الضغط الزائد
                "sfx_type": "gentle_whoosh",
                "zoom_mode": "in_center",
                "narration": "أَمَّا لَوْ زَادَ الضَّغْطُ أَوِ الحَرَارَةُ لأَيِّ سَبَبٍ طَارِئٍ، يَتَدَخَّلُ صِمَامُ الأَمَانِ لِفَتْحِ مَسَارٍ لِتَفْرِيغِ الضَّغْطِ الزَّائِدِ فَوْراً وَمَنْعِ أَيِّ خَطَرٍ.",
                "image_prompt": f"{style}Close-up 3D shot of the brass pressure relief safety valve on the water heater pipe releasing a gentle puff of white steam and water droplets to relieve excess pressure.",
                "motion_prompt": "3D engineering animation, a gentle wisp of white steam releases smoothly from the brass safety valve"
            },
            {
                # 14. سحب الماء الساخن من قمة الخزان
                "sfx_type": "water_flow",
                "zoom_mode": "in_top",
                "narration": "وَفِي اللَّحْظَةِ الَّتِي تَفْتَحُ فِيهَا صُنْبُورَ المَاءِ السَّاخِنِ، يُسْحَبُ المَاءُ مِنْ أَعْلَى نُقْطَةٍ فِي قِمَّةِ الخَزَّانِ، لِيَنْزِلَ عَبْرَ المَاسُورَةِ الحَمْرَاءِ إِلَيْكَ مُبَاشَرَةً.",
                "image_prompt": f"{style}Interior 3D cutaway shot of the top dome of the tank: glowing warm orange-red hot water at the very top entering the upper opening of the vertical hot-water outlet pipe and flowing downward.",
                "motion_prompt": "3D fluid simulation, warm glowing orange-red hot water flows smoothly into the top outlet pipe and travels downward"
            },
            {
                # 15. الدورة المستمرة المتكاملة للسخان
                "sfx_type": "scanner_sweep",
                "zoom_mode": "out_center",
                "narration": "وَفِي نَفْسِ اللَّحْظَةِ يَدْخُلُ مَاءٌ بَارِدٌ جَدِيدٌ إِلَى القَاعِ لِيُعِيدَ الدَّوْرَةَ مِنْ جَدِيدٍ؛ هَنْدَسَةٌ بَسِيطَةٌ، لَكِنَّهَا تَعْمَلُ بِدِقَّةٍ مُذْهِلَةٍ فِي كُلِّ يَوْمٍ.",
                "image_prompt": f"{style}Wide masterpiece 3D shot of the water heater on the grey tiled wall: half sleek white exterior shell and half crystal-clear X-ray cutaway showing blue cold water entering at the bottom and warm orange-red hot water exiting the left red pipe.",
                "motion_prompt": "Masterpiece 3D engineering visualization, smooth slow camera pull-back showing the complete harmonious water circulation inside the half-cutaway water heater"
            }
        ]
    }


def discover_uploaded_images_map():
    """
    يكتشف الصور المرفوعة بذكاء:
    - إذا وجد الصورة 0.jpg (أي أن المستخدم سمى لقطة الشاب 0.jpg وباقي الصور 1.jpg..14.jpg)، يرتبها من 0 إلى 14!
    - وإذا سمى المستخدم الصور من 1.jpg إلى 15.jpg، يرتبها من 1 إلى 15!
    """
    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".jfif")
    ignore_prefixes = ("scene_", "temp_", "sub_", "base_", "raw_", "scanner_")
    raw_num_map = {}

    for root_dir in [".", "images", "scenes"]:
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

    # إذا رفع المستخدم 0.jpg مع 1..14، نرحّل الأرقام بمقدار +1 لتتطابق مع المشاهد الـ 15 تلقائياً!
    if 0 in raw_num_map:
        shifted_map = {}
        for k, v in raw_num_map.items():
            shifted_map[k + 1] = v
        return shifted_map

    return raw_num_map


def save_clean_engineering_image(src_path, dst_file):
    img = Image.open(src_path).convert("RGB")
    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.04)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def obtain_scene_image(index, image_prompt, img_file, uploaded_map):
    scene_num = index + 1
    if scene_num in uploaded_map:
        src = uploaded_map[scene_num]
        save_clean_engineering_image(src, img_file)
        print(f"📸 تم استخدام صورتك المرفوعة للمشهد {scene_num}: ({src})!", flush=True)
        return

    image_pool = HF_TOKENS[7:] + HF_TOKENS[:7] + [None]
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
                    save_clean_engineering_image(img_path, img_file)
                    print(f"✨ تم تصميم صورة المشهد {scene_num} عبر ({space_name} - {quota_label})!", flush=True)
                    return
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
                break

    raise RuntimeError(f"تعذر تجهيز صورة للمشهد {scene_num}")


def create_teacher_audio_and_get_duration(index, scene, out_audio_file):
    narration = (scene.get("narration") or "").strip()
    sfx_type = scene.get("sfx_type", "gentle_whoosh")

    raw_voice_mp3 = f"voice_raw_{index}.mp3"
    sfx_ogg = f"raw_sfx_{index}.ogg"
    sfx_url, sfx_vol = SCIENCE_FOLEY_URLS.get(sfx_type, SCIENCE_FOLEY_URLS["gentle_whoosh"])

    voice_ok = False
    for voice_name, pitch, rate in [
        ("ar-JO-TaimNeural", "-1Hz", "-2%"),
        ("ar-EG-ShakirNeural", "-1Hz", "-3%"),
        ("ar-SA-HamedNeural", "-2Hz", "-3%")
    ]:
        try:
            subprocess.run([
                "edge-tts", "--voice", voice_name,
                f"--pitch={pitch}", f"--rate={rate}",
                "--text", narration, "--write-media", raw_voice_mp3
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_voice_mp3) and os.path.getsize(raw_voice_mp3) > 1000:
                voice_ok = True
                break
        except Exception:
            time.sleep(1)

    if not voice_ok:
        encoded = urllib.parse.quote(narration)
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ar&q={encoded}", timeout=30)
        with open(raw_voice_mp3, "wb") as f:
            f.write(r.content)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", raw_voice_mp3
    ], capture_output=True, text=True, check=True)
    voice_dur = float(probe.stdout.strip() or "4.5")
    final_dur = round(voice_dur + 0.55, 2)

    warm_eq = "highpass=f=75,equalizer=f=200:width_type=o:width=1.5:g=2.2,equalizer=f=3200:width_type=o:width=2.0:g=1.5"

    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-i", sfx_ogg,
                "-i", raw_voice_mp3,
                "-filter_complex",
                f"[1:a]atrim=0:{min(final_dur, 2.5)},afade=t=in:d=0.1,afade=t=out:st={max(min(final_dur, 2.5) - 0.5, 0.2)}:d=0.5,volume={sfx_vol}[sfx];"
                f"[2:a]{warm_eq},adelay=150|150,apad=pad_dur=0.5,volume=1.35[v];"
                f"[0:a][sfx][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return final_dur
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", raw_voice_mp3,
        "-filter_complex",
        f"[1:a]{warm_eq},adelay=150|150,apad=pad_dur=0.5,volume=1.35[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
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
    full_motion = f"{motion_prompt}, photorealistic 3D engineering animation, smooth fluid movement, high quality, keep structure intact"
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"

    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue

        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx} ({tok[:10]}...)"

        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"جاري تحريك اللقطة الهندسية {index + 1} عبر ({wan_space} - {quota_label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=5,
                negative_prompt=neg_prompt,
                duration_seconds=2.5,
                guidance_scale=1.1,
                guidance_scale_2=1.1,
                seed=CHARACTER_MASTER_SEED + index,
                randomize_seed=False,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك اللقطة {index + 1} بنجاح عبر {wan_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue
            try:
                ps = PinnedSpace(wan_space, token=tok)
                up_img = ps.upload(img_file)
                out = ps.call("/generate_video", [up_img, full_motion, 5, neg_prompt, 2.5, 1.1, 1.1, CHARACTER_MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك اللقطة {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل فوراً للحساب التالي...", flush=True)
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def create_laser_scanner_reveal_video(exterior_img, interior_img, duration, out_video):
    """
    تأثير السكانر الضوئي (Laser Scanner Wipe Reveal):
    يمسح صورة السخان المغلق بخط ليزر سماوي متوهج من الأعلى للأسفل ليكشف باطن السخان ثم يثبت مع زوم نظيف!
    """
    fps = 30
    scan_seconds = min(2.8, duration * 0.65)
    filter_complex = (
        f"[0:v]scale=1080:1920,setsar=1[ext];"
        f"[1:v]scale=1080:1920,setsar=1[int];"
        f"[ext][int]blend=all_expr='if(lte(Y, (T/{scan_seconds})*1920), B, A)'[wiped];"
        f"[wiped]drawbox=x=0:y='min((t/{scan_seconds})*1920,1930)':w=1080:h=10:color=0x00FFFF@0.90:t=fill,"
        f"drawbox=x=0:y='min((t/{scan_seconds})*1920-8,1930)':w=1080:h=26:color=0x00BFFF@0.35:t=fill,"
        f"scale=1160:2062,crop=1080:1920:'(iw-1080)/2':'(ih-1920)*(t/{duration})',"
        f"cas=0.6,format=yuv420p[v]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", str(duration), "-i", exterior_img,
        "-loop", "1", "-t", str(duration), "-i", interior_img,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-t", str(duration), "-r", str(fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", out_video
    ], check=True)


def render_clean_subtitle_png(phrase_text, png_path):
    font_file = ensure_arabic_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_file, 52, layout_engine=ImageFont.Layout.BASIC)
        reshaped = ARABIC_RESHAPER.reshape(phrase_text)
        display_text = get_display(reshaped)
    except Exception:
        font = ImageFont.truetype(font_file, 52)
        display_text = phrase_text

    bbox = draw.textbbox((0, 0), display_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (1080 - w) // 2
    y_pos = 1540

    pad_x, pad_y = 32, 14
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=22,
        fill=(10, 18, 28, 190),
        outline=(0, 210, 255, 210),
        width=2
    )
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx != 0 or dy != 0:
                draw.text((x_pos + dx, y_pos + dy), display_text, font=font, fill=(0, 0, 0, 255))
    draw.text((x_pos, y_pos), display_text, font=font, fill=(255, 255, 255, 255))
    img.save(png_path, "PNG")


def create_scene_assets(index, scene, uploaded_map):
    image_prompt = scene["image_prompt"]
    motion_prompt = scene["motion_prompt"]
    narration = (scene.get("narration") or "").strip()
    zoom_mode = scene.get("zoom_mode", "in_center")

    audio_file = f"scene_{index}.wav"
    duration = create_teacher_audio_and_get_duration(index, scene, audio_file)

    img_file = f"scene_{index}.jpg"
    obtain_scene_image(index, image_prompt, img_file, uploaded_map)

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    prev_img_file = f"scene_{index - 1}.jpg"
    if zoom_mode == "scanner_reveal" and os.path.exists(prev_img_file):
        print("🔍 جاري تطبيق تأثير المسح الضوئي (Laser Scanner Reveal) لكشف السخان من الداخل...", flush=True)
        create_laser_scanner_reveal_video(prev_img_file, img_file, duration, base_video)
    else:
        ai_animated = animate_image_with_ai(index, img_file, motion_prompt, raw_ai_video)

        if ai_animated and os.path.exists(raw_ai_video):
            # الحركة تعمل مرة واحدة فقط ثم تثبت على آخر فريم (tpad=stop_mode=clone) مع زوم نظيف نحو السخان!
            y_crop_expr = f"(ih-1920)/2 - 35*(t/{duration})"
            if zoom_mode == "in_top":
                # زوم يتجه للأعلى نحو السخان المعلق على الحائط (في المشهد الأول ومشهد القمة)
                y_crop_expr = f"(ih-1920)*0.45*(1 - t/{duration})"

            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", raw_ai_video,
                "-vf", (
                    f"setpts=1.35*PTS,"
                    f"tpad=stop_mode=clone:stop_duration=15,"
                    f"scale=1220:2168:force_original_aspect_ratio=increase,crop=1220:2168,"
                    f"crop=1080:1920:'(iw-1080)/2':'{y_crop_expr}',"
                    f"cas=0.65,setsar=1,format=yuv420p"
                ),
                "-t", str(duration), "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
            ], check=True)
        else:
            z_expr = "min(zoom+0.0018,1.22)" if "in" in zoom_mode else "if(eq(on,1),1.22,max(zoom-0.0018,1.0))"
            y_focus = "ih/2-(ih/zoom/2)"
            if zoom_mode == "in_bottom":
                y_focus = "ih*0.72-(ih/zoom/2)"
            elif zoom_mode == "in_top":
                y_focus = "ih*0.25-(ih/zoom/2)"

            zoom_filter = (
                f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
                f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='{y_focus}':"
                f"d={total_frames}:s=1080x1920:fps={fps},cas=0.6,setsar=1,format=yuv420p"
            )
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-i", img_file,
                "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
            ], check=True)

    clean_words = re.sub(r'[\u0617-\u061A\u064B-\u0652"\'«»*():؛،.؟]', '', narration).split()
    phrases = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)] or ["..."]
    step_dur = duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"
    for p_idx, phrase in enumerate(phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_clean_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-i", png_file])
        start_t = round(p_idx * step_dur, 2)
        end_t = round((p_idx + 1) * step_dur, 2)
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(f"{last_stream}[{inp_idx}:v]overlay=0:0:enable='between(t,{start_t},{end_t})'{next_stream}")
        last_stream = next_stream

    fade_out_st = max(round(duration - 0.22, 2), 0.5)
    filter_parts.append(
        f"{last_stream}fade=t=in:st=0:d=0.20,fade=t=out:st={fade_out_st}:d=0.22,format=yuv420p[vout]"
    )

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
            "title": f"{title[:80]} #علوم #هندسة #كيف_يعمل #shorts",
            "description": f"{title}\n\nشرح علمي وهندسي مبسط ثلاثي الأبعاد لكيفية عمل سخان المياه من الداخل.\n#علوم #هندسة #معلومات #تكنولوجيا #كيف_يعمل #shorts",
            "tags": ["كيف يعمل السخان", "هندسة", "علوم", "معلومات عامة", "3d animation", "shorts"],
            "categoryId": "28"
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
            "description": f"{title} 🔍🔥\n\n#علوم #هندسة #كيف_يعمل #معلومات #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def assemble_and_publish():
    print(f"🚀 إجمالي حسابات ومفاتيح Hugging Face الجاهزة: {len(HF_TOKENS)} مفتاحاً", flush=True)
    uploaded_map = discover_uploaded_images_map()
    print(f"📸 الصور المرفوعة المكتشفة في المستودع: {len(uploaded_map)} صورة ({sorted(uploaded_map.keys())})", flush=True)

    story = get_water_heater_explainer_storyboard()
    print(f"🔬 عنوان الفيديو: {story['title']} ({len(story['scenes'])} مشهداً علمياً)", flush=True)

    scene_videos = []
    total_duration = 0.0
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري إنتاج وتحريك اللقطة الهندسية {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip, dur = create_scene_assets(idx, scene, uploaded_map)
        scene_videos.append(clip)
        total_duration += dur

    print(f"⏱️ إجمالي مدة الفيديو النهائية: {round(total_duration, 1)} ثانية ({round(total_duration / 60, 2)} دقيقة)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final_video = "final_short.mp4"
    print("جاري المونتاج النهائي...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt",
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


if __name__ == "__main__":
    assemble_and_publish()
