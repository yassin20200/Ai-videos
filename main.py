import os
import re
import math
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-AndrewMultilingualNeural").strip() or "en-US-AndrewMultilingualNeural"

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
FONT_BOLD_PATH = "Montserrat-ExtraBold.ttf"
MASTER_SEED = 909101

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "splash": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.28),
    "turbine": ("https://actions.google.com/sounds/v1/science_fiction/sci_fi_osh.ogg", 0.24),
    "alarm": ("https://actions.google.com/sounds/v1/alarms/beep_short.ogg", 0.28),
    "clunk": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.32),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.26),
    "bubbles": ("https://actions.google.com/sounds/v1/water/air_woosh_underwater.ogg", 0.26),
    "pop": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.28),
    "cheer": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.28)
}

STYLE_PREFIX = (
    "Masterpiece 3D isometric cutaway engineering diorama render, Blender Cycles & Unreal Engine 5 studio lighting, "
    "clean stylized 3D scientific visualization on a sunny riverside concrete pad with blue sky and fluffy white 3D clouds, "
    "ultra-crisp 8k, vertical 9:16, no text, no watermarks. "
)

NUCLEAR_PLANT_STAGES = [
    {
        "id": 0,
        "sfx": "splash",
        "narration": "If you drop uranium into a tank of water, the uranium gets hot, and you have a nuclear reactor.",
        "image_prompt": (
            f"{STYLE_PREFIX}A transparent 3D cutaway glass cylindrical water tank on a concrete pad with a yellow gantry crane "
            f"lowering glowing warm orange vertical uranium fuel rods into crystal-clear blue water with rising white bubbles."
        ),
        "motion_prompt": "3D engineering animation, glowing orange uranium fuel rods submerged in the transparent water tank as white bubbles rise smoothly upward",
        "callouts": [
            {"target": (540, 1060), "box": (770, 940), "text": "URANIUM FUEL", "color": (215, 132, 42)},
            {"target": (420, 1180), "box": (250, 1260), "text": "WATER TANK", "color": (78, 158, 215)}
        ]
    },
    {
        "id": 1,
        "sfx": "turbine",
        "narration": "But hot water doesn't make electricity. So you let it boil, and use steam to spin a turbine connected to a generator.",
        "image_prompt": (
            f"{STYLE_PREFIX}A 3D cutaway boiling nuclear water reactor tank connected by a sleek silver overhead steam pipe "
            f"to a 3D cutaway spinning multi-blade metal steam turbine and a green electric generator lighting up a glowing streetlamp."
        ),
        "motion_prompt": "3D engineering animation, white steam flows through the pipe spinning the metal turbine blades rapidly as the streetlamp glows brightly",
        "callouts": [
            {"target": (460, 740), "box": (270, 680), "text": "STEAM PIPE", "color": (120, 145, 165)},
            {"target": (620, 1080), "box": (580, 910), "text": "3D TURBINE", "color": (110, 128, 145)},
            {"target": (810, 1080), "box": (820, 910), "text": "GENERATOR", "color": (58, 168, 130)}
        ]
    },
    {
        "id": 2,
        "sfx": "alarm",
        "narration": "However, uranium keeps getting hotter and hotter. So you slide control rods between the fuel to absorb the reaction and cool it down.",
        "image_prompt": (
            f"{STYLE_PREFIX}Close-up 3D cutaway of the nuclear reactor core inside the water tank: dark metallic grey cylindrical control rods "
            f"sliding vertically down from the top cap right between the glowing orange uranium fuel rods in bubbling blue water."
        ),
        "motion_prompt": "3D engineering cutaway animation, dark metallic control rods slide smoothly downward between the glowing orange fuel rods in bubbling water",
        "gauge_mode": "cool_down",
        "callouts": [
            {"target": (540, 860), "box": (770, 780), "text": "CONTROL RODS", "color": (68, 78, 88)}
        ]
    },
    {
        "id": 3,
        "sfx": "clunk",
        "narration": "In an emergency, you need to stop it fast. So you hang the rods above the core on electromagnets. If power cuts out, they drop right in.",
        "image_prompt": (
            f"{STYLE_PREFIX}Close-up 3D cutaway of the top of the nuclear reactor vessel: red and gold electromagnet coils holding "
            f"the dark grey control rods suspended above the glowing uranium fuel core inside the transparent water tank."
        ),
        "motion_prompt": "3D engineering animation, the dark control rods drop downward into the glowing reactor core as water bubbles rise",
        "callouts": [
            {"target": (540, 720), "box": (760, 650), "text": "ELECTROMAGNETS", "color": (215, 55, 45)}
        ]
    },
    {
        "id": 4,
        "sfx": "bubbles",
        "narration": "But water touching uranium gets radioactive, and right now it spins your turbine. So you seal it in a closed loop to boil clean water in a second loop.",
        "image_prompt": (
            f"{STYLE_PREFIX}Two side-by-side 3D cutaway cylindrical tanks: the left reactor tank with glowing uranium connected by red and blue "
            f"heat-exchanger pipes to a glowing copper U-tube coil boiling clean blue water inside the right secondary tank."
        ),
        "motion_prompt": "3D fluid and thermal animation, glowing heat flows through the copper heat-exchanger coil boiling clean blue water in the second tank",
        "callouts": [
            {"target": (460, 1080), "box": (310, 1250), "text": "CLOSED LOOP", "color": (215, 132, 42)},
            {"target": (680, 960), "box": (790, 800), "text": "SECONDARY LOOP", "color": (78, 158, 215)}
        ]
    },
    {
        "id": 5,
        "sfx": "splash",
        "narration": "Next, you condense the steam back into water to reuse it. You can cool it with river water, but the river heats up enough to cook the fish.",
        "image_prompt": (
            f"{STYLE_PREFIX}3D cutaway view of blue and red cooling pipes running from the power plant condenser into a blue river "
            f"where a warm orange thermal water plume surrounds stylized 3D fish swimming in the river."
        ),
        "motion_prompt": "3D animation, warm water flows from the pipes into the blue river as stylized 3D fish swim through the water",
        "gauge_mode": "river_70",
        "callouts": [
            {"target": (520, 1020), "box": (320, 880), "text": "STEAM -> WATER", "color": (78, 158, 215)}
        ]
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "narration": "So you build a giant cooling tower. Hot water rains down inside, air carries heat up, and that cloud on top is just pure water vapor.",
        "image_prompt": (
            f"{STYLE_PREFIX}A giant 3D semi-transparent X-ray cutaway concrete hyperboloid nuclear cooling tower showing hot water spraying "
            f"down like rain inside while white fluffy pure H2O water vapor clouds billow out of the wide top opening into the blue sky."
        ),
        "motion_prompt": "3D engineering cutaway animation, water sprays downward inside the cooling tower while white steam clouds rise smoothly out of the top",
        "callouts": [
            {"target": (540, 1020), "box": (290, 920), "text": "COOLING TOWER", "color": (128, 122, 112)},
            {"target": (540, 580), "box": (770, 520), "text": "PURE H2O VAPOR", "color": (78, 158, 215)}
        ]
    },
    {
        "id": 7,
        "sfx": "clunk",
        "narration": "If anything leaks, radiation could escape. So you build a steel and concrete containment dome over a meter thick around the reactor.",
        "image_prompt": (
            f"{STYLE_PREFIX}A massive 3D cutaway reinforced grey concrete and steel dome structure over a meter thick enclosing "
            f"the glowing nuclear reactor vessel and secondary heat-exchanger tank inside, with the cooling tower in the background."
        ),
        "motion_prompt": "3D architectural cutaway animation, smooth camera push-in showing the thick reinforced concrete and steel containment dome around the reactor",
        "callouts": [
            {"target": (540, 660), "box": (540, 520), "text": "CONTAINMENT DOME (+1m)", "color": (105, 112, 120)}
        ]
    },
    {
        "id": 8,
        "sfx": "alarm",
        "narration": "If the pumps fail, the core will overheat. So you add backup generators, and a high water tank that floods the core by gravity alone.",
        "image_prompt": (
            f"{STYLE_PREFIX}Beside the 3D cutaway concrete containment dome stand yellow 3D backup diesel generators and a tall steel tower "
            f"holding an elevated blue water tank with a pipe pouring cooling water down into the reactor core by gravity."
        ),
        "motion_prompt": "3D engineering animation, blue cooling water flows downward from the elevated gravity water tank into the glowing reactor core",
        "gauge_mode": "overheat_1064",
        "callouts": [
            {"target": (310, 1120), "box": (260, 960), "text": "BACKUP GENERATORS", "color": (212, 160, 36)},
            {"target": (330, 760), "box": (330, 610), "text": "GRAVITY WATER TANK", "color": (78, 158, 215)}
        ]
    },
    {
        "id": 9,
        "sfx": "bubbles",
        "narration": "Used nuclear fuel stays hot for years, so you submerge it in a deep water pool where it glows bright blue.",
        "image_prompt": (
            f"{STYLE_PREFIX}Close-up 3D cutaway of a deep rectangular concrete spent nuclear fuel pool filled with crystal-clear water, "
            f"where submerged metallic fuel racks at the bottom emit a mesmerizing bright cyan-blue Cherenkov radiation glow."
        ),
        "motion_prompt": "3D animation, submerged nuclear fuel assemblies glow with a bright electric blue Cherenkov light under rippling clear water",
        "callouts": [
            {"target": (540, 1060), "box": (540, 840), "text": "SPENT FUEL POOL (CHERENKOV GLOW)", "color": (45, 142, 220)}
        ]
    },
    {
        "id": 10,
        "sfx": "pop",
        "narration": "One tiny uranium fuel pellet, the size of a gummy bear, produces as much electricity as an entire ton of coal.",
        "image_prompt": (
            f"{STYLE_PREFIX}3D macro comparison on a clean studio platform: a single tiny metallic grey cylindrical uranium fuel pellet "
            f"next to a small red gummy bear on the left, balanced against a massive pile of black coal rocks on the right."
        ),
        "motion_prompt": "Clean 3D product animation, subtle camera orbit around the tiny metallic uranium fuel pellet and the massive pile of black coal",
        "show_pellet_card": True,
        "callouts": []
    },
    {
        "id": 11,
        "sfx": "cheer",
        "narration": "And congratulations! You just built a nuclear power plant.",
        "image_prompt": (
            f"{STYLE_PREFIX}Wide panoramic masterpiece 3D cutaway diorama of the complete working nuclear power plant on the sunny river pad: "
            f"containment dome, primary and secondary loops, spinning turbine, green generator, giant cooling tower with white steam, and blue spent fuel pool."
        ),
        "motion_prompt": "Masterpiece 3D diorama animation, smooth panoramic camera pull-back showing the complete nuclear power plant operating in harmony",
        "show_confetti": True,
        "callouts": []
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


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def generate_3d_stage_image(stage_idx, image_prompt, dst_jpg):
    """
    توليد صورة ثلاثية الأبعاد فائقة الجودة (8K 3D Isometric Cutaway) تلقائياً
    عبر FLUX.1-dev و FLUX.1-schnell باستخدام مفاتيح Hugging Face الـ 17!
    """
    image_pool = HF_TOKENS[7:] + HF_TOKENS[:7] + [None]
    for space_name, steps in [("black-forest-labs/FLUX.1-dev", 24), ("black-forest-labs/FLUX.1-schnell", 4)]:
        for tok in image_pool:
            tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
            if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
                continue
            label = "Free Server IP" if tok is None else f"HF Token ({tok[:10]}...)"
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
                    img = Image.open(img_path).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
                    img = ImageEnhance.Contrast(img).enhance(1.05)
                    img = ImageEnhance.Color(img).enhance(1.10)
                    img = img.filter(ImageFilter.UnsharpMask(radius=1.3, percent=115, threshold=3))
                    img.save(dst_jpg, "JPEG", quality=98)
                    print(f"✨ Generated 8K 3D Render for Stage {stage_idx + 1} via ({space_name} - {label})!", flush=True)
                    return
            except Exception as e:
                if is_quota_error(e):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue
   
