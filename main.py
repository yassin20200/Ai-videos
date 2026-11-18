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

print("🚀 Starting Uncut 16:9 Documentary Studio (Part 1: Roman Concrete - 100% Uncut Studio Audio)...", flush=True)

VIDEO_W, VIDEO_H = 1920, 1080  # Horizontal 16:9 Long-Form YouTube format
ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-AndrewMultilingualNeural").strip() or "en-US-AndrewMultilingualNeural"

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

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FONT_BOLD_PATH = "Montserrat-ExtraBold.ttf"
MASTER_SEED = 202601

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.18),
    "crumble": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.22),
    "fire": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.18),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.20),
    "water": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.20)
}

STYLE_PREFIX = (
    "Masterpiece stylized 3D cinematic documentary render, Unreal Engine 5 studio lighting, "
    "rich textures, ultra-crisp 8k horizontal 16:9 widescreen, no text, no watermarks. "
)

ROMAN_CONCRETE_SCENES = [
    {
        "id": 0,
        "sfx": "waves",
        "lip_sync": True,
        "narration": (
            "Look at modern concrete skyscrapers, bridges, and highways built with the most advanced technology of the twenty-first century. "
            "Within just fifty to eighty years, steel-reinforced modern concrete begins to crack, rust, and crumble into dust. "
            "Yet across the Mediterranean Sea, massive Roman harbors built two thousand years ago are still standing completely intact, "
            "battered by violent ocean waves every single day, and somehow growing stronger every century."
        ),
        "image_prompt": f"{STYLE_PREFIX}A wise Roman master architect in a toga facing the camera directly ready to speak, between a cracked modern bridge and an intact Roman harbor.",
        "motion_prompt": "Natural 3D character speaking directly to the camera with expressive lip movement, subtle head nods, and natural breathing"
    },
    {
        "id": 1,
        "sfx": "whoosh",
        "lip_sync": False,
        "narration": (
            "To understand this ancient mystery, travel to the heart of Rome and step inside the Pantheon, built nearly two millennia ago. "
            "Above your head hangs the largest unreinforced concrete dome on the planet, spanning one hundred and forty-two feet across open air. "
            "There is not a single rod of steel inside that dome. If modern engineers poured a dome of that exact size using standard modern concrete without steel today, "
            "it would collapse under its own weight the moment the scaffolding was removed."
        ),
        "image_prompt": f"{STYLE_PREFIX}Wide interior shot of the Roman Pantheon dome with a golden sunbeam shining down through the oculus.",
        "motion_prompt": "Majestic 3D camera pan inside the Roman Pantheon as golden dust motes float in the sunbeam shining through the dome oculus"
    },
    {
        "id": 2,
        "sfx": "crumble",
        "lip_sync": False,
        "narration": (
            "Why does modern concrete fail so quickly compared to Roman structures? "
            "Modern Portland cement is designed for speed and mass production, mixed smoothly with sand, gravel, and water to harden fast. "
            "When salt water seeps into microscopic pores inside modern concrete, it attacks the internal steel bars. "
            "The rusting steel expands up to six times its original volume, exploding the surrounding concrete from the inside out."
        ),
        "image_prompt": f"{STYLE_PREFIX}3D cutaway cross-section of a modern concrete pillar underwater with rusting internal steel rebar cracking the concrete.",
        "motion_prompt": "3D engineering cutaway animation, orange rust spreads on the internal steel bars as cracks form across the grey concrete pillar"
    },
    {
        "id": 3,
        "sfx": "waves",
        "lip_sync": False,
        "narration": (
            "In stark contrast, ancient Roman marine concrete did not fear the ocean; it actually needed seawater to reach its ultimate strength. "
            "Two thousand years ago, Roman emperors constructed gigantic artificial harbors at Caesarea and Pozzuoli by pouring thousands of tons of concrete directly into the open sea. "
            "Today, marine geologists testing those submerged Roman piers have discovered that they are significantly harder now than the day they were poured."
        ),
        "image_prompt": f"{STYLE_PREFIX}Split underwater and surface shot of an ancient Roman harbor with wooden ships above and a massive submerged concrete pier below.",
        "motion_prompt": "3D underwater cinematic animation, blue ocean waves ripple against the ancient submerged Roman concrete pier"
    },
    {
        "id": 4,
        "sfx": "fire",
        "lip_sync": False,
        "narration": (
            "For centuries, historians assumed the Romans just got lucky with their raw materials. "
            "But in the first century AD, the Roman author Pliny the Elder wrote a cryptic clue in his encyclopedia of natural history. "
            "He described how volcanic ash from the Gulf of Naples, mixed with limestone and seawater, transformed into a single stone mass, "
            "impenetrable to the waves and growing stronger every day it remained underwater."
        ),
        "image_prompt": f"{STYLE_PREFIX}Pliny the Elder writing on a parchment scroll by candlelight with Mount Vesuvius glowing through an arched window behind him.",
        "motion_prompt": "3D atmospheric animation, candlelight flickers over the parchment scroll while volcanic smoke rises from Mount Vesuvius in the distance"
    },
    {
        "id": 5,
        "sfx": "fire",
        "lip_sync": True,
        "narration": (
            "We did not build for a single generation; we built for eternity. "
            "Our secret began in the shadow of Mount Vesuvius, where we harvested special volcanic ash called pozzolana, rich in silica and alumina. "
            "When we mixed that volcanic ash with roasted limestone and dropped it into wooden molds beneath the sea, "
            "we triggered a chemical reaction that modern builders completely forgot."
        ),
        "image_prompt": f"{STYLE_PREFIX}The Roman master engineer facing the camera directly ready to speak, holding a bowl of volcanic ash in front of glowing lime kilns.",
        "motion_prompt": "Natural 3D character speaking directly to the camera with realistic lip sync and hand gestures while fire glows in the background"
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "lip_sync": False,
        "narration": (
            "When twentieth-century scientists finally placed ancient Roman concrete under high-powered electron microscopes, they noticed something bizarre. "
            "Scattered throughout the grey Roman mortar were thousands of tiny, bright white mineral chunks, just a few millimeters wide, known as lime clasts. "
            "For decades, modern engineers dismissed these white chunks as sloppy, careless mixing by ancient workers who failed to stir their mortar properly."
        ),
        "image_prompt": f"{STYLE_PREFIX}Macro 3D view of a slice of ancient Roman concrete under a microscope showing bright white mineral chunks scattered in grey stone.",
        "motion_prompt": "Smooth 3D macro camera push-in focusing on the glowing white mineral lime clasts embedded inside the ancient grey concrete"
    },
    {
        "id": 7,
        "sfx": "whoosh",
        "lip_sync": False,
        "narration": (
            "Calling the Romans sloppy made no sense at all. The Romans were the most disciplined, meticulous engineers of the ancient world, "
            "spending years perfecting every recipe before building an aqueduct or a harbor. "
            "Recently, a team of researchers at MIT looked closer at those tiny white chunks using advanced X-ray imaging, "
            "and realized those white flecks were not a mistake. They were the secret weapon."
        ),
        "image_prompt": f"{STYLE_PREFIX}Scientists in a high-tech lab examining a chunk of Roman concrete under a glowing cyan X-ray laser scanner.",
        "motion_prompt": "3D laboratory animation, a glowing cyan X-ray laser beam scans across the Roman concrete sample highlighting the white pockets"
    },
    {
        "id": 8,
        "sfx": "fire",
        "lip_sync": False,
        "narration": (
            "Instead of mixing their concrete cold with water the way modern construction crews do, the ancient Romans used a dangerous process called hot mixing. "
            "They combined reactive quicklime, burnt limestone powder, directly with volcanic ash and water. "
            "This triggered a violent exothermic chemical reaction, heating the entire concrete mixture to over two hundred degrees Celsius, "
            "boiling and fusing the minerals together."
        ),
        "image_prompt": f"{STYLE_PREFIX}Roman workers pouring white quicklime and volcanic ash into a wooden trough with boiling steam and glowing orange heat.",
        "motion_prompt": "3D dramatic animation, thick white steam and glowing orange heat rise from the boiling Roman mortar mix"
    },
    {
        "id": 9,
        "sfx": "crumble",
        "lip_sync": False,
        "narration": (
            "Because of that intense two-hundred-degree heat inside the Roman mixer, tiny pockets of calcium did not dissolve. "
            "Instead, they baked into brittle, porous white spheres trapped inside the hardening stone wall, "
            "like millions of microscopic medicine capsules waiting to be activated centuries in the future."
        ),
        "image_prompt": f"{STYLE_PREFIX}3D X-ray cutaway inside the Roman concrete wall showing bright white spherical calcium pockets locked inside the stone.",
        "motion_prompt": "3D scientific cutaway animation, glowing white spherical calcium capsules pulse gently inside the dark stone matrix"
    },
    {
        "id": 10,
        "sfx": "whoosh",
        "lip_sync": True,
        "narration": (
            "When we tested this Roman recipe in the laboratory, we were stunned by what happened next. "
            "These tiny white lime clasts act as an automatic self-healing system trapped inside the wall. "
            "The moment a tiny crack forms in the concrete, rainwater or seawater seeps into the crack and hits one of those ancient calcium pockets."
        ),
        "image_prompt": f"{STYLE_PREFIX}A modern materials scientist in a white lab coat facing the camera directly ready to speak, holding a Roman concrete sample.",
        "motion_prompt": "Natural 3D scientist character speaking directly to the camera with accurate lip movement and natural facial expressions"
    },
    {
        "id": 11,
        "sfx": "water",
        "lip_sync": False,
        "narration": (
            "The instant water touches that trapped white lime clast, the calcium dissolves and flows directly into the open fracture. "
            "As it reacts with volcanic ash along the edges of the crack, it rapidly recrystallizes into solid calcium carbonate and a rare mineral called Al-tobermorite, "
            "sealing the crack shut from the inside before it can ever spread."
        ),
        "image_prompt": f"{STYLE_PREFIX}Macro 3D cutaway of water hitting a white calcium sphere inside a concrete crack and crystallizing to seal the crack shut.",
        "motion_prompt": "3D microscopic animation, glowing white calcium crystals grow and seal the dark crack inside the concrete wall"
    },
    {
        "id": 12,
        "sfx": "water",
        "lip_sync": False,
        "narration": (
            "To prove this wasn't just a theory, the MIT scientists mixed two batches of concrete: one using the modern recipe, and one using the ancient Roman hot-mixing formula. "
            "They intentionally cracked both blocks down the middle and ran a slow stream of water through them. "
            "The modern concrete stayed broken and leaked continuously, while the Roman block completely healed its own cracks within just fourteen days."
        ),
        "image_prompt": f"{STYLE_PREFIX}Side-by-side lab test showing a leaking cracked modern concrete block on the left and a sealed self-healed Roman concrete block on the right.",
        "motion_prompt": "3D laboratory comparison animation, water leaks from the left block while the right Roman block remains completely sealed"
    },
    {
        "id": 13,
        "sfx": "waves",
        "lip_sync": False,
        "narration": (
            "Today, producing modern cement accounts for nearly eight percent of all global carbon dioxide emissions, "
            "largely because modern structures have to be torn down and rebuilt every few decades. "
            "By reviving this lost two-thousand-year-old Roman formula, modern engineers are now beginning to pour new seawalls and bridges "
            "that can heal their own fractures and last for centuries."
        ),
        "image_prompt": f"{STYLE_PREFIX}A massive modern coastal seawall and bridge against ocean waves with a glowing structural blueprint overlay.",
        "motion_prompt": "3D cinematic camera glide along the massive coastal seawall as ocean waves crash against it harmlessly"
    },
    {
        "id": 14,
        "sfx": "whoosh",
        "lip_sync": True,
        "narration": (
            "Two thousand years ago, without computers, without electron microscopes, and without steel reinforcement, "
            "Roman builders mastered a level of chemical engineering that outlasted empires. "
            "And Roman concrete is only the first chapter. In Part Two, we dive to the bottom of the Aegean Sea "
            "to uncover a two-thousand-year-old geared bronze computer that shouldn't exist."
        ),
        "image_prompt": f"{STYLE_PREFIX}The narrator facing the camera directly at sunset with the Roman Pantheon on one side and a glowing bronze geared mechanism on the other.",
        "motion_prompt": "Natural 3D narrator speaking directly to the camera with realistic lip sync as golden sunset light shines behind him"
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
        raise RuntimeError("Connection ended without receiving video")

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
            raise RuntimeError(f"Video URL not found: {output_data}")
        content = self.http.get(file_url).content
        if len(content) < 10000:
            raise RuntimeError("Downloaded video file is too small")
        Path(dst).write_bytes(content)


def ensure_english_font():
    if os.path.exists(FONT_BOLD_PATH) and os.path.getsize(FONT_BOLD_PATH) > 10000:
        return FONT_BOLD_PATH
    try:
        url = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-ExtraBold.ttf"
        r = requests.get(url, timeout=30)
        if r.ok:
            with open(FONT_BOLD_PATH, "wb") as f:
                f.write(r.content)
            return FONT_BOLD_PATH
    except Exception:
        pass
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def discover_uploaded_images_map():
    """فحص فولدر images أولاً ثم scenes ثم المجلد الرئيسي"""
    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".jfif")
    ignore_prefixes = ("scene_", "stage_", "temp_", "sub_", "base_", "raw_", "stretched_", "nuclear_")
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


def save_clean_widescreen_image(src_path, dst_file):
    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = VIDEO_W / VIDEO_H
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) > 0.25:
        bg = img.resize((VIDEO_W, VIDEO_H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        new_h = VIDEO_H
        new_w = int(src_w * (new_h / src_h))
        fg = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        bg.paste(fg, ((VIDEO_W - new_w) // 2, 0))
        img = bg
    else:
        img = img.resize((VIDEO_W, VIDEO_H), Image.Resampling.LANCZOS)

    img = ImageEnhance.Contrast(img).enhance(1.04)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def obtain_scene_image(index, image_prompt, dst_jpg, uploaded_map):
    scene_num = index + 1
    if scene_num in uploaded_map:
        src = uploaded_map[scene_num]
        save_clean_widescreen_image(src, dst_jpg)
        print(f"📸 Using your uploaded Gemini image for Scene {scene_num}: ({src})!", flush=True)
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
                        width=1792,
                        height=1024,
                        guidance_scale=3.5,
                        num_inference_steps=steps,
                        api_name="/infer"
                    )
                else:
                    res = client.predict(
                        prompt=image_prompt,
                        seed=MASTER_SEED,
                        randomize_seed=False,
                        width=1792,
                        height=1024,
                        num_inference_steps=steps,
                        api_name="/infer"
                    )
                img_path = res[0] if isinstance(res, (list, tuple)) else res
                if isinstance(img_path, dict) and "path" in img_path:
                    img_path = img_path["path"]
                if isinstance(img_path, str) and os.path.exists(img_path):
                    save_clean_widescreen_image(img_path, dst_jpg)
                    return
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
                break

    raise RuntimeError(f"Failed to obtain image for Scene {scene_num}")


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


def animate_scene_with_lipsync_or_wan(index, scene, start_img, next_img, out_raw_video):
    motion_prompt = scene["motion_prompt"]
    is_lipsync = scene.get("lip_sync", False)
    full_motion = (
        f"{motion_prompt}, realistic lip movement synchronized with speech, expressive talking face, high quality 3D"
        if is_lipsync else
        f"{motion_prompt}, smooth continuous 3D cinematic documentary animation, high quality"
    )
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

    if not is_lipsync and next_img and os.path.exists(next_img):
        for tok in all_pool[:3]:
            tok_key = "FLF_IP" if tok is None else f"FLF_{tok[:12]}"
            if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
                continue
            try:
                flf_space = "multimodalart/wan-2-2-first-last-frame"
                client = Client(flf_space, token=tok, verbose=False)
                res = client.predict(
                    start_image=handle_file(start_img),
                    end_image=handle_file(next_img),
                    prompt=full_motion,
                    negative_prompt=neg_prompt,
                    duration_seconds=3.0,
                    steps=4,
                    guidance_scale=1.0,
                    guidance_scale_2=1.0,
                    seed=MASTER_SEED + index,
                    randomize_seed=False,
                    api_name="/generate_video"
                )
                v_path = extract_video_path(res)
                if v_path:
                    shutil.copyfile(v_path, out_raw_video)
                    print(f"🔗 Scene {index + 1} smoothly morphed (Start->End Frame) via {flf_space}!", flush=True)
                    return True
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
                break

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue
        label = "Free Server IP" if tok is None else f"HF Token #{pool_idx} ({tok[:10]}...)"
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"🎬 Animating Scene {index + 1} ({'Lip-Sync Speaking' if is_lipsync else '3D Documentary'}) via ({wan_space} - {label})...", flush=True)
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
                print(f"🎉 Scene {index + 1} animated via {wan_space} ({label})!", flush=True)
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
                print(f"🎉 Scene {index + 1} animated via {wan_space} Pinned ({label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def vtt_time_to_seconds(t_str):
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return 0.0


def parse_vtt_into_5word_phrases(vtt_path, fallback_text, total_dur, delay_sec=0.15):
    """
    قراءة توقيت الكلمات الحقيقي من ملف الـ VTT الناتج من محرك الصوت
    وتقسيمها إلى بطاقات من 5 كلمات متزامنة بالمللي ثانية مع صوت المعلق!
    """
    phrases = []
    if os.path.exists(vtt_path):
        try:
            content = Path(vtt_path).read_text(encoding="utf-8", errors="ignore")
            blocks = re.split(r"\n\s*\n", content)
            for b in blocks:
                lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
                time_line = next((ln for ln in lines if "-->" in ln), None)
                if not time_line:
                    continue
                t_parts = time_line.split("-->")
                st = vtt_time_to_seconds(t_parts[0]) + delay_sec
                et = vtt_time_to_seconds(t_parts[1].split()[0]) + delay_sec
                text_lines = [ln for ln in lines if "-->" not in ln and not ln.startswith("WEBVTT") and not ln.isdigit()]
                cue_text = " ".join(text_lines)
                clean_words = re.sub(r'["\'«»*():;,.?!—-]', '', cue_text).split()
                if not clean_words or et <= st:
                    continue

                chunks = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)]
                c_step = (et - st) / len(chunks)
                for c_i, ch in enumerate(chunks):
                    c_start = round(st + c_i * c_step, 2)
                    c_end = round(st + (c_i + 1) * c_step, 2)
                    phrases.append((ch, c_start, min(c_end, total_dur)))
        except Exception:
            pass

    if phrases:
        return phrases

    clean_words = re.sub(r'["\'«»*():;,.?!—-]', '', fallback_text).split()
    chunks = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)] or ["..."]
    step = total_dur / len(chunks)
    return [(ch, round(idx * step, 2), round((idx + 1) * step, 2)) for idx, ch in enumerate(chunks)]


def build_uncut_crystal_clear_audio(seg_idx, scene, out_wav):
    """
    توليد الصوت الوثائقي الواضح بالكامل بدون أي فلتر قص (Zero Silenceremove / Zero Truncation)!
    - يحول الصوت أولاً إلى WAV غير مضغوط ويقيس طوله الحقيقي بالمللي ثانية.
    - يضيف 0.80 ثانية راحة في نهاية كل مشهد حتى تُسمع آخر كلمة وآخر نفس بوضوح تام 100%!
    """
    text = scene["narration"]
    sfx_key = scene["sfx"]

    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    raw_vtt = f"seg_sub_{seg_idx}.vtt"
    clean_voice_wav = f"seg_clean_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=-2%",
                "--text", text,
                "--write-media", raw_mp3,
                "--write-subtitles", raw_vtt
            ], check=True, timeout=45, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 1000:
                voice_ok = True
                break
        except Exception:
            time.sleep(0.5)

    if not voice_ok:
        encoded = urllib.parse.quote(text[:450])
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en&q={encoded}", timeout=25)
        with open(raw_mp3, "wb") as f:
            f.write(r.content)

    # معالجة صوتية استوديو نقية (Warm Studio EQ + Broadcast Compressor) بدون أي silenceremove نهائياً!
    studio_audio_chain = (
        "highpass=f=70,"
        "equalizer=f=165:width_type=o:width=1.5:g=2.4,"
        "equalizer=f=3500:width_type=o:width=2.0:g=1.8,"
        "acompressor=threshold=-18dB:ratio=2.2:attack=15:release=180:makeup=1.5"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_mp3,
        "-af", studio_audio_chain,
        "-ar", "44100", "-ac", "2", clean_voice_wav
    ], check=True)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", clean_voice_wav
    ], capture_output=True, text=True, check=True)
    v_dur = float(probe.stdout.strip() or "18.0")

    # إضافة 0.80 ثانية كاملة بعد انتهاء آخر حرف في الصوت لضمان عدم بتر أي كلمة نهائياً!
    final_dur = round(v_dur + 0.80, 2)
    timed_phrases = parse_vtt_into_5word_phrases(raw_vtt, text, final_dur, delay_sec=0.15)

    sfx_url, sfx_vol = SFX_LIBRARY.get(sfx_key, SFX_LIBRARY["waves"])
    try:
        r = requests.get(sfx_url, timeout=15)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-i", sfx_ogg,
                "-i", clean_voice_wav,
                "-filter_complex",
                f"[1:a]atrim=0:{min(final_dur, 3.0)},afade=t=in:d=0.1,afade=t=out:st={max(min(final_dur, 3.0) - 0.6, 0.2)}:d=0.6,volume={sfx_vol}[s];"
                f"[2:a]adelay=150|150,apad=pad_dur=0.65,volume=1.40[v];"
                f"[0:a][s][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
            ], check=True)
            return final_dur, timed_phrases
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", clean_voice_wav,
        "-filter_complex",
        "[1:a]adelay=150|150,apad=pad_dur=0.65,volume=1.40[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
    ], check=True)
    return final_dur, timed_phrases


def render_widescreen_subtitle_png(phrase_text, png_path):
    font_file = ensure_english_font()
    img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 46)

    words = phrase_text.upper().split()
    full_text = " ".join(words)
    bbox = draw.textbbox((0, 0), full_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (VIDEO_W - w) // 2
    y_pos = 920

    pad_x, pad_y = 34, 16
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 10)],
        radius=22,
        fill=(10, 14, 22, 215),
        outline=(255, 200, 45, 235),
        width=3
    )

    curr_x = x_pos
    for idx, word in enumerate(words):
        word_str = word + (" " if idx < len(words) - 1 else "")
        w_box = draw.textbbox((0, 0), word_str, font=font)
        word_w = w_box[2] - w_box[0]
        color = (255, 215, 45, 255) if idx == len(words) - 1 else (255, 255, 255, 255)

        for dx in (-3, 0, 3):
            for dy in (-3, 0, 3):
                if dx != 0 or dy != 0:
                    draw.text((curr_x + dx, y_pos + dy), word_str, font=font, fill=(0, 0, 0, 255))
        draw.text((curr_x, y_pos), word_str, font=font, fill=color)
        curr_x += word_w

    img.save(png_path, "PNG")


def build_scene_clip(index, scene, all_scene_imgs):
    audio_file = f"scene_audio_{index}.wav"
    duration, timed_phrases = build_uncut_crystal_clear_audio(index, scene, audio_file)

    start_img = all_scene_imgs[index]
    next_img = all_scene_imgs[index + 1] if index + 1 < len(all_scene_imgs) else None

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(round(duration * fps))

    ai_animated = animate_scene_with_lipsync_or_wan(index, scene, start_img, next_img, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_video
        ], capture_output=True, text=True, check=True)
        raw_vid_dur = max(float(v_probe.stdout.strip() or "3.0"), 1.0)
        stretch_factor = round((duration + 0.25) / raw_vid_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_video,
            "-vf", (
                f"setpts={stretch_factor}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=3,"
                f"scale=2112:1188:force_original_aspect_ratio=increase,crop=2112:1188,"
                f"crop={VIDEO_W}:{VIDEO_H}:'(iw-{VIDEO_W})/2 - 35*(t/{duration})':'(ih-{VIDEO_H})/2 - 20*(t/{duration})',"
                f"cas=0.65,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", start_img,
            "-vf", (
                f"scale=2304:1296:force_original_aspect_ratio=increase,crop=2304:1296,"
                f"zoompan=z='min(zoom+0.0005,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={total_frames + 15}:s={VIDEO_W}x{VIDEO_H}:fps={fps},cas=0.6,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"
    for p_idx, (phrase, start_t, end_t) in enumerate(timed_phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_widescreen_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-t", str(duration), "-i", png_file])
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:shortest=1:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    fade_out_st = max(round(duration - 0.25, 2), 0.5)
    filter_parts.append(
        f"{last_stream}fade=t=in:st=0:d=0.22,fade=t=out:st={fade_out_st}:d=0.25,format=yuv420p[vout]"
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


def upload_long_video_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    clean_title = title[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": (
                f"{title}\n\n"
                "Part 1 of Lost Ancient Engineering Secrets: How Ancient Rome built self-healing underwater concrete stronger than modern buildings.\n"
                "#history #engineering #ancientrome #documentary #science"
            ),
            "tags": ["roman concrete", "ancient engineering", "self healing concrete", "history documentary", "ancient rome", "science"],
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube Long-Form] Uploaded successfully: https://youtu.be/{res['id']}", flush=True)


def assemble_and_publish():
    title = "How The Ancient Romans Built Concrete Stronger Than Modern Buildings (Part 1)"
    uploaded_img_map = discover_uploaded_images_map()
    print(f"📸 Uploaded Gemini images found in 'images/': {len(uploaded_img_map)} ({sorted(uploaded_img_map.keys())})", flush=True)

    all_scene_imgs = []
    for idx, scene in enumerate(ROMAN_CONCRETE_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_img_map)
        all_scene_imgs.append(img_file)

    scene_videos = []
    total_dur = 0.0
    for idx, scene in enumerate(ROMAN_CONCRETE_SCENES):
        print(f"--- Producing Uncut Scene {idx + 1}/15 ---", flush=True)
        clip, dur = build_scene_clip(idx, scene, all_scene_imgs)
        scene_videos.append(clip)
        total_dur += dur

    print(f"⏱️ Total Uncut Documentary Duration: {round(total_dur, 1)}s ({round(total_dur / 60, 2)} minutes)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_long.mp4"
    final_video = "final_roman_concrete_part1.mp4"

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.004",
        "-filter_complex",
        "[1:a]lowpass=f=240[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-vf", f"scale={VIDEO_W}:{VIDEO_H},setsar=1,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
        "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
        "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
    ], check=True)

    print("🚀 Publishing Part 1 Long-Form Documentary to YouTube...", flush=True)
    for token in YT_REFRESH_TOKENS:
        try:
            upload_long_video_to_youtube(final_video, title, token)
        except Exception as e:
            print(f"[YouTube Error] {e}", flush=True)


assemble_and_publish()
