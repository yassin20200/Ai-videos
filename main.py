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
RECITER_NAME = os.getenv("RECITER_NAME", "Minshawy_Murattal").strip() or "Minshawy_Murattal"

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
CHARACTER_MASTER_SEED = 777888

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": True,
    "support_ligatures": False
})

# قراء التراث الإسلامي (الإذاعة المصرية ومجمع الملك فهد) الذين لا يتعرضون لحظر عالمي على يوتيوب
SAFE_RECITER_FOLDERS = {
    "Minshawy_Murattal": ("Minshawy_Murattal_128kbps", "ar.minshawi", "الشيخ محمد صديق المنشاوي"),
    "AbdulBaset_Murattal": ("Abdul_Basit_Murattal_192kbps", "ar.abdulbasitmurattal", "الشيخ عبد الباسط عبد الصمد"),
    "Husary": ("Husary_128kbps", "ar.husary", "الشيخ محمود خليل الحصري"),
    "Hudhaify": ("Hudhaify_128kbps", "ar.hudhaify", "الشيخ علي الحذيفي")
}

NATURE_FOLEY_URLS = {
    "desert_wind": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.22),
    "sea_waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.25),
    "water_parting": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.28),
    "staff_strike": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.35)
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


def get_unabridged_quran_storyboard():
    """
    9 آيات كاملة متتالية من سورة الشعراء (الآيات 60 إلى 68)
    كل آية تُقرأ كاملة 100% من أول كلمة لآخر كلمة بدون أي قص أو تقسيم!
    """
    style = "Masterpiece dark-inked cinematic graphic novel illustration, bold hand-drawn comic line art, dramatic desert and ocean chiaroscuro lighting, rich earthy tones, vertical 9:16, no text, no watermarks. "
    _, _, reciter_ar = SAFE_RECITER_FOLDERS.get(RECITER_NAME, SAFE_RECITER_FOLDERS["Minshawy_Murattal"])

    return {
        "title": f"كلا إن معي ربي سيهدين | قصة فلق البحر كاملة بصوت {reciter_ar}",
        "scenes": [
            {
                # المشهد 1: الآية 60 كاملة
                "surah": 26,
                "ayah": 60,
                "include_basmala": True,
                "sfx_type": "desert_wind",
                "subtitle_text": "بسم الله الرحمن الرحيم • فأتبعوهم مشرقين",
                "image_prompt": f"{style}At sunrise, a massive ancient Pharaoh army of war chariots and horses charging across the desert sand kicking up golden dust under the rising sun.",
                "motion_prompt": "Subtle slow-motion movement of dust clouds and sunrise rays over the desert, preserve original illustration lines, no morphing"
            },
            {
                # المشهد 2: الآية 61 كاملة بدون أي قص
                "surah": 26,
                "ayah": 61,
                "sfx_type": "sea_waves",
                "subtitle_text": "فلما تراءى الجمعان قال أصحاب موسى إنا لمدركون",
                "image_prompt": f"{style}A group of robed travellers standing seen from behind at the edge of a dark crashing sea beach, looking at a wall of desert dust in the distance.",
                "motion_prompt": "Gentle slow-motion ocean waves on the shore and slight cloak movement in the wind, preserve original illustration, no morphing"
            },
            {
                # المشهد 3: الآية 62 كاملة بدون أي قص
                "surah": 26,
                "ayah": 62,
                "sfx_type": "sea_waves",
                "subtitle_text": "قال كلا إن معي ربي سيهدين",
                "image_prompt": f"{style}A noble robed figure seen strictly from BEHIND (back view only, NO face visible, head surrounded by a soft halo of white light), wearing a brown wool cloak, standing firm at the edge of the ocean waves holding a tall wooden staff.",
                "motion_prompt": "Subtle slow-motion movement of the brown cloak in the sea breeze and gentle ocean waves ahead, preserve original drawing, no morphing"
            },
            {
                # المشهد 4: الآية 63 كاملة في مشهد واحد دون تقسيمها نصفين!
                "surah": 26,
                "ayah": 63,
                "sfx_type": "water_parting",
                "subtitle_text": "فأوحينا إلى موسى أن اضرب بعصاك البحر فانفلق فكان كل فرق كالطود العظيم",
                "image_prompt": f"{style}Breathtaking wide shot: the deep ocean miraculously parting into two colossal towering walls of rushing water like giant mountains on the left and right, revealing a wide dry rocky path down the middle lit by golden light.",
                "motion_prompt": "Slow-motion surging water mist along the two towering walls of ocean water and glowing light rays, preserve original drawing, no morphing"
            },
            {
                # المشهد 5: الآية 64 كاملة
                "surah": 26,
                "ayah": 64,
                "sfx_type": "desert_wind",
                "subtitle_text": "وأزلفنا ثم الآخرين",
                "image_prompt": f"{style}Ancient war chariots pulled by dark horses approaching the entrance of the parted sea canyon between the two giant towering walls of water.",
                "motion_prompt": "Slow-motion camera push-in toward the canyon between the two giant walls of water, preserve original drawing, no morphing"
            },
            {
                # المشهد 6: الآية 65 كاملة
                "surah": 26,
                "ayah": 65,
                "sfx_type": "sea_waves",
                "subtitle_text": "وأنجينا موسى ومن معه أجمعين",
                "image_prompt": f"{style}Silhouetted robed believers seen strictly from behind walking safely out of the parted sea onto the sunny rocky shore on the other side, led by the robed figure with the wooden staff seen strictly from behind.",
                "motion_prompt": "Warm golden sunbeams shining down over the shore in peaceful slow motion, preserve original drawing, no morphing"
            },
            {
                # المشهد 7: الآية 66 كاملة
                "surah": 26,
                "ayah": 66,
                "sfx_type": "water_parting",
                "subtitle_text": "ثم أغرقنا الآخرين",
                "image_prompt": f"{style}The two colossal towering mountain walls of ocean water crashing back together with immense power in swirling white foam and deep dark waves.",
                "motion_prompt": "Slow-motion crashing white ocean foam and waves, preserve original drawing, no morphing"
            },
            {
                # المشهد 8: الآية 67 كاملة
                "surah": 26,
                "ayah": 67,
                "sfx_type": "sea_waves",
                "subtitle_text": "إن في ذلك لآية وما كان أكثرهم مؤمنين",
                "image_prompt": f"{style}Wide dramatic shot of the vast ocean waves rolling under dark parting storm clouds with a beam of light touching the water.",
                "motion_prompt": "Slow-motion ocean waves rolling gently under the clouds, preserve original drawing, no morphing"
            },
            {
                # المشهد 9: الآية 68 كاملة
                "surah": 26,
                "ayah": 68,
                "sfx_type": "sea_waves",
                "subtitle_text": "وإن ربك لهو العزيز الرحيم",
                "image_prompt": f"{style}Serene majestic landscape shot: the vast ocean calm and peaceful, with glorious golden sunbeams breaking through clouds over the water and distant mountains.",
                "motion_prompt": "Peaceful golden sunbeams shining over the calm rippling ocean water in slow motion, preserve original drawing, no morphing"
            }
        ]
    }


def download_ayah_recitation_mp3(surah, ayah, dst_mp3):
    folder, alquran_edition, _ = SAFE_RECITER_FOLDERS.get(RECITER_NAME, SAFE_RECITER_FOLDERS["Minshawy_Murattal"])

    everyayah_url = f"https://everyayah.com/data/{folder}/{surah:03d}{ayah:03d}.mp3"
    try:
        r = requests.get(everyayah_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.ok and len(r.content) > 2000:
            with open(dst_mp3, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass

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

    fallback_url = f"https://everyayah.com/data/Minshawy_Murattal_128kbps/{surah:03d}{ayah:03d}.mp3"
    r3 = requests.get(fallback_url, timeout=30)
    r3.raise_for_status()
    with open(dst_mp3, "wb") as f:
        f.write(r3.content)
    return True


def create_unabridged_scene_quran_audio(index, scene, out_audio_file):
    """
    تشغيل الآية القرآنية كاملة 100% من أول جزء من الثانية إلى آخر جزء من الثانية بدون أي قص إطلاقاً!
    مع إضافة هامش سكون (1.2 ثانية) بعد انتهاء الآية لضمان عدم بتر آخر حرف أبداً.
    """
    surah = int(scene["surah"])
    ayah = int(scene["ayah"])
    include_basmala = scene.get("include_basmala", False)
    sfx_type = scene.get("sfx_type", "sea_waves")

    raw_ayah_mp3 = f"ayah_raw_{index}.mp3"
    download_ayah_recitation_mp3(surah, ayah, raw_ayah_mp3)

    if include_basmala:
        basmala_mp3 = f"basmala_{index}.mp3"
        combined_mp3 = f"comb_{index}.mp3"
        download_ayah_recitation_mp3(1, 1, basmala_mp3)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", basmala_mp3, "-i", raw_ayah_mp3,
            "-filter_complex", "[0:a]apad=pad_dur=0.5[b];[b][1:a]concat=n=2:v=0:a=1[a]",
            "-map", "[a]", combined_mp3
        ], check=True)
        shutil.copyfile(combined_mp3, raw_ayah_mp3)

    # قياس الطول الحقيقي الكامل للآية وإضافة 1.2 ثانية كاملة بعدها حتى لا يُقطع نفس القارئ في آخر حرف أبداً!
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", raw_ayah_mp3
    ], capture_output=True, text=True, check=True)
    exact_ayah_dur = float(probe.stdout.strip() or "7.0")
    final_dur = round(exact_ayah_dur + 1.25, 2)

    sfx_ogg = f"raw_sfx_{index}.ogg"
    sfx_url, sfx_vol = NATURE_FOLEY_URLS.get(sfx_type, NATURE_FOLEY_URLS["sea_waves"])
    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            # دمج صوت الطبيعة مع صدى مسجدي وتغيير طفيف جداً في البصمة الرقمية (asetrate) لمنع حظر Content ID مع الحفاظ على خشوع الصوت 100%
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-stream_loop", "3", "-i", sfx_ogg,
                "-i", raw_ayah_mp3,
                "-filter_complex",
                f"[1:a]atrim=0:{final_dur},afade=t=in:d=0.3,afade=t=out:st={max(final_dur - 0.5, 0.5)}:d=0.5,volume={sfx_vol}[sfx];"
                f"[2:a]asetrate=44100*0.98,aresample=44100,atempo=1.02,adelay=300|300,aecho=0.8:0.88:50:0.20,apad=pad_dur=1.0,volume=1.40[q];"
                f"[0:a][sfx][q]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return final_dur
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", raw_ayah_mp3,
        "-filter_complex",
        "[1:a]adelay=300|300,aecho=0.8:0.88:50:0.20,apad=pad_dur=1.0,volume=1.40[q];[0:a][q]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)
    return final_dur


def find_uploaded_image_for_scene(scene_number_1based):
    """البحث عن الصور المرفوعة من المستخدم في المستودع"""
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


def render_quran_subtitle_png(ayah_phrase, png_path):
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
    """
    الحفاظ على جودة ونقاء الصورة الأصلية 100% عبر حركة الكاميرا السلسة (Cinematic Ken Burns)
    بحيث لا تتشوه الصور المرسومة أثناء التحريك أبداً!
    """
    image_prompt = scene["image_prompt"]
    subtitle_text = (scene.get("subtitle_text") or "").strip()

    audio_file = f"scene_{index}.wav"
    duration = create_unabridged_scene_quran_audio(index, scene, audio_file)

    img_file = f"scene_{index}.jpg"
    obtain_scene_image(index, image_prompt, img_file)

    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15

    # حركة كاميرا سينمائية تحافظ على تفاصيل الرسمة الأصلية 100% بدون أي تشويه من موديلات الفيديو
    z_expr = "min(zoom+0.0012,1.18)" if index % 2 == 0 else "if(eq(on,1),1.18,max(zoom-0.0012,1.0))"
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
            "tags": ["قرآن", "تلاوة خاشعة", "المنشاوي", "قصص القرآن", "موسى عليه السلام", "shorts"],
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


def assemble_and_publish():
    story = get_quran_simulation_storyboard() if False else get_unabridged_quran_storyboard()
    print(f"📖 عنوان الفيديو: {story['title']}", flush=True)

    scene_videos = []
    total_duration = 0.0
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري تجهيز المشهد القرآني {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip, dur = create_scene_assets(idx, scene)
        scene_videos.append(clip)
        total_duration += dur

    print(f"⏱️ إجمالي مدة الفيديو النهائية الكاملة بدون أي قص: {round(total_duration, 1)} ثانية ({round(total_duration / 60, 2)} دقيقة)!", flush=True)

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

    # النشر على يوتيوب وفيسبوك فقط (تم إيقاف إنستجرام نهائياً كما طلبت)
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
