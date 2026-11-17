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

print("🚀 Starting Long-Form 16:9 Documentary Studio (Target: 04:35 / 275.0s Exact)...", flush=True)

TARGET_TOTAL_VIDEO_SECONDS = 275.0  # 4 minutes and 35 seconds exact
VIDEO_W, VIDEO_H = 1920, 1080       # Horizontal 16:9 Long-Form YouTube format

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
MASTER_SEED = 196206

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.24),
    "alarm": ("https://actions.google.com/sounds/v1/alarms/beep_short.ogg", 0.25),
    "scrape": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.24),
    "thump": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.28),
    "wind": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.24),
    "water": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.25)
}

STYLE_PREFIX = (
    "Masterpiece stylized 3D cinematic historical thriller render, Unreal Engine 5 studio lighting, "
    "rich atmospheric textures, dramatic shadows, ultra-crisp 8k horizontal 16:9 widescreen, no text, no watermarks. "
)

# 15 فصلاً متكاملاً لقصة الهروب من ألكاتراز 1962 (مصممة لتغطية 4 دقائق و35 ثانية بتشويق مستمر)
ALCATRAZ_SCENES = [
    {
        "id": 0,
        "sfx": "waves",
        "narration": (
            "In the middle of the freezing, shark-infested waters of San Francisco Bay sits Alcatraz Island, "
            "a fortress built on jagged rock that the United States government promised was one hundred percent escape-proof. "
            "Yet in June of nineteen sixty-two, three men pulled off the most brilliant prison break in human history, "
            "using nothing but stolen spoons, raincoats, and painted dummy heads."
        ),
        "image_prompt": f"{STYLE_PREFIX}Alcatraz Island prison at night in 1962 sitting on a jagged rock in stormy ocean waves while a yellow searchlight sweeps from the guard tower.",
        "motion_prompt": "Cinematic 3D widescreen animation, stormy ocean waves crash against Alcatraz island at night as the yellow searchlight beam sweeps through the mist"
    },
    {
        "id": 1,
        "sfx": "alarm",
        "narration": (
            "On the morning of June twelfth, nineteen sixty-two, the loud metallic clanging of the morning bell echoed through Cellblock B. "
            "Every prisoner stood up for the routine headcount, except for three men who appeared to be fast asleep under their blankets. "
            "When a guard reached through the iron bars and shoved the pillow of inmate Frank Morris, "
            "the prisoner's head rolled right off the bed and crashed onto the concrete floor."
        ),
        "image_prompt": f"{STYLE_PREFIX}Inside a dim 1962 Alcatraz prison cell at dawn, a guard reaches through the bars and a painted dummy head with real hair rolls off the pillow onto the floor.",
        "motion_prompt": "Suspenseful 3D animation, the uniformed prison guard steps back in shock as the painted dummy head lies on the concrete cell floor"
    },
    {
        "id": 2,
        "sfx": "thump",
        "narration": (
            "The mastermind behind this audacious plot was Frank Lee Morris, a career criminal with a genius-level IQ of one hundred and thirty-three "
            "who had already escaped from multiple prisons across the country. "
            "From the very first hour Morris arrived on Alcatraz in January nineteen sixty, he didn't look for ways to survive his sentence; "
            "he immediately began searching for a structural weakness in the fortress."
        ),
        "image_prompt": f"{STYLE_PREFIX}Frank Morris kneeling beneath a rusty metal sink inside his concrete prison cell, shining a tiny match light at a small metal air vent grille near the floor.",
        "motion_prompt": "3D cinematic animation, the warm match flame flickers in the dim prison cell as the prisoner examines the metal air vent under the sink"
    },
    {
        "id": 3,
        "sfx": "scrape",
        "narration": (
            "Morris noticed a tiny detail that the prison architects had overlooked for decades. "
            "Constant exposure to the damp, salty ocean air blowing in from San Francisco Bay had slowly eaten away at the concrete walls. "
            "Down beneath his cell sink sat a small metal air vent, just four inches high and eight inches wide, "
            "surrounded by crumbling, salt-damaged mortar that could be chipped away."
        ),
        "image_prompt": f"{STYLE_PREFIX}Macro close-up of a prisoner's hand holding a stolen metal dining spoon scraping away crumbling grey concrete around a small iron ventilation grille.",
        "motion_prompt": "Close-up 3D animation, the metal spoon scrapes against the crumbling concrete wall as dust particles fall slowly to the floor"
    },
    {
        "id": 4,
        "sfx": "wind",
        "narration": (
            "Knowing a job this complex required a team, Morris quietly recruited three inmates occupying adjacent cells: "
            "brothers John and Clarence Anglin, who were expert swimmers, and Allen West, who worked on the prison maintenance crew. "
            "Every afternoon in the windy prison yard, the four men stood together whispering blueprints, "
            "assigning tasks, and smuggling tiny tools back into their cells."
        ),
        "image_prompt": f"{STYLE_PREFIX}Four prisoners in 1962 denim jackets huddled together in a corner of the misty Alcatraz prison yard whispering while armed guards watch from a high walkway.",
        "motion_prompt": "3D cinematic animation, mist drifts across the prison yard as the four inmates whisper together cautiously while guards patrol above"
    },
    {
        "id": 5,
        "sfx": "scrape",
        "narration": (
            "Digging through solid concrete with stolen dining spoons and discarded saw blades was agonizingly slow, "
            "and a single suspicious sound would send them straight to solitary confinement. "
            "So the men timed their heavy digging to coincide with the daily prison music hour. "
            "While Frank Morris stood at the front of his cell loudly playing an accordion, "
            "his partners behind the walls used a makeshift drill built from a stolen vacuum cleaner motor."
        ),
        "image_prompt": f"{STYLE_PREFIX}Inside the cellblock, a prisoner plays an accordion by the cell bars while behind him in the shadows another prisoner uses a makeshift drill on the wall.",
        "motion_prompt": "3D dramatic animation, the prisoner plays the accordion by the bars while sparks and dust fly from the hidden wall hole in the shadows"
    },
    {
        "id": 6,
        "sfx": "thump",
        "narration": (
            "To hide the growing gaping holes in their walls during surprise daytime cell inspections, "
            "the prisoners crafted fake ventilation grilles out of stiff cardboard painted with dark grey soap and dust. "
            "After nearly a full year of relentless nighttime scraping, the men finally broke through into an unguarded, pitch-black utility corridor "
            "running directly behind the cellblock, filled with massive vertical water and sewage pipes."
        ),
        "image_prompt": f"{STYLE_PREFIX}Frank Morris squeezing through the jagged hole behind his cell sink into a dark secret utility corridor filled with huge vertical rusty iron pipes.",
        "motion_prompt": "3D suspense animation, the prisoner crawls into the narrow dark pipe corridor as dust motes float in a dim shaft of light"
    },
    {
        "id": 7,
        "sfx": "wind",
        "narration": (
            "At night, after the guards locked down the tiers, Morris and the Anglin brothers climbed thirty feet up those rusty iron pipes "
            "to the flat, empty top of the cellblock roof, thirty feet above the floor. "
            "Up there in the dark shadows, hidden behind hanging blankets, they established a secret midnight workshop. "
            "Over the course of months, they collected over fifty rubber raincoats stolen from prison laundry bins."
        ),
        "image_prompt": f"{STYLE_PREFIX}Three prisoners crouching under hanging blankets on top of the dark cellblock roof, stitching together fifty yellow-and-black rubber raincoats into a raft.",
        "motion_prompt": "3D cinematic animation, the three prisoners work under a dim hanging light stitching yellow rubber raincoats into a large raft"
    },
    {
        "id": 8,
        "sfx": "scrape",
        "narration": (
            "Getting off the prison rock was only half the battle; swimming over a mile through forty-eight-degree water with strong currents was suicide. "
            "Using sewing needles and heavy thread, the inmates stitched the fifty raincoats into a fourteen-foot-long inflatable rubber raft. "
            "Then, using a brilliant piece of prison engineering, they pressed the rubber seams against scalding-hot steam pipes in the corridor "
            "to melt and vulcanize the rubber until it was completely airtight."
        ),
        "image_prompt": f"{STYLE_PREFIX}Close-up shot in the secret corridor: prisoners pressing the seams of the yellow rubber raincoat raft against a hot white steam pipe to seal it airtight.",
        "motion_prompt": "3D engineering animation, white steam rises gently as the rubber raft seams are pressed against the hot metal pipe"
    },
    {
        "id": 9,
        "sfx": "thump",
        "narration": (
            "To inflate their raft quickly on the beach without running out of breath, they modified a broken wooden concertina musical instrument "
            "to work as a high-volume air bellows, and carved sturdy paddles out of scrap plywood. "
            "Meanwhile, to buy themselves nine crucial hours of head start before the morning count, "
            "they sculpted remarkably lifelike dummy heads out of soap, toilet paper, and concrete dust, topped with real hair from the barbershop."
        ),
        "image_prompt": f"{STYLE_PREFIX}Close-up on a dim prison table showing three lifelike sculpted dummy heads made of soap and paper, painted with flesh tones and real human hair.",
        "motion_prompt": "Slow 3D camera push-in across the three eerie lifelike painted dummy heads sitting on the wooden prison table"
    },
    {
        "id": 10,
        "sfx": "alarm",
        "narration": (
            "On the night of June eleventh, nineteen sixty-two, everything was finally ready. "
            "Right after lights out at nine-thirty PM, the men placed the dummy heads onto their pillows and stuffed rolled-up clothes under the blankets. "
            "Morris and the two Anglin brothers crawled into the dark corridor, but disaster struck Allen West: "
            "the quick-drying cement he used to hold his fake grille had hardened too much, trapping him inside his cell as the others moved on."
        ),
        "image_prompt": f"{STYLE_PREFIX}Inside the dark prison cell at night, a lifelike dummy head rests under the blanket on the bed while Frank Morris slips through the hole under the sink.",
        "motion_prompt": "Tense 3D night animation, moonlight shines through the cell bars onto the dummy head in bed as the prisoner vanishes into the wall hole"
    },
    {
        "id": 11,
        "sfx": "wind",
        "narration": (
            "Climbing up the vertical ventilation shaft in the darkness, Morris and the Anglin brothers pried open the heavy iron fanilator on the roof "
            "using a homemade crowbar, popping the rivets with a loud metallic snap that somehow went unnoticed by the guards. "
            "Clutching their heavy bundle of raincoats and wooden paddles, they crept across the high cellhouse roof, "
            "dropping flat into the shadows every time the blinding guard tower searchlight swept past."
        ),
        "image_prompt": f"{STYLE_PREFIX}Three prisoners crouching low on the high wind-swept roof of Alcatraz at night carrying their folded raft as a bright yellow searchlight sweeps past.",
        "motion_prompt": "3D thriller animation, the golden searchlight beam sweeps across the wet rooftop as the three prisoners crouch in the dark shadows"
    },
    {
        "id": 12,
        "sfx": "waves",
        "narration": (
            "Sliding fifty feet down a cast-iron kitchen exhaust pipe on the north side of the building, "
            "the three men climbed over two twelve-foot barbed-wire fences and reached the dark, rocky shoreline on the northeast corner of the island. "
            "Working in total silence in the blind spot of the searchlight, they pumped the wooden concertina bellows, "
            "inflating their fourteen-foot raincoat raft as icy waves crashed against their ankles."
        ),
        "image_prompt": f"{STYLE_PREFIX}At the rocky water's edge of Alcatraz at night, the three prisoners frantically inflate their yellow raincoat raft as dark ocean waves crash around them.",
        "motion_prompt": "3D action animation, dark ocean waves splash against the rocks as the three men pump the yellow raft at the water's edge"
    },
    {
        "id": 13,
        "sfx": "water",
        "narration": (
            "Around ten PM, Frank Morris, John Anglin, and Clarence Anglin pushed off from the rocks into the freezing black waters of San Francisco Bay. "
            "Using their homemade plywood paddles, they vanished into the thick, swirling silver fog heading north toward Angel Island, "
            "two miles away. By the time Allen West finally chipped his cell vent open and reached the roof hours later, "
            "his partners were long gone into the night."
        ),
        "image_prompt": f"{STYLE_PREFIX}The three men paddling their makeshift raincoat raft into thick silver fog across the dark choppy waters of San Francisco Bay toward distant city lights.",
        "motion_prompt": "Epic 3D atmospheric animation, the raincoat raft glides into the swirling silver fog over dark rippling waves toward the distant horizon"
    },
    {
        "id": 14,
        "sfx": "waves",
        "narration": (
            "The next morning, the largest manhunt in FBI history was launched across the bay. "
            "Searchers found a single wooden paddle floating near Angel Island and a waterproof plastic bag containing the Anglin brothers' family photos, "
            "but no bodies ever washed ashore. Nine months later, Alcatraz was shut down forever, "
            "and to this day, the mystery remains unsolved: did they drown in the bay, or did three men with spoons beat the impossible?"
        ),
        "image_prompt": f"{STYLE_PREFIX}At dawn on the foggy shore of Angel Island, two 1962 FBI agents in trench coats hold a washed-up wooden paddle, staring out at the empty misty bay.",
        "motion_prompt": "Cinematic 3D closing shot, morning mist drifts over the calm bay waters as the two FBI agents stand on the rocky shore"
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
    """حفظ الصورة بمقاس الفيديو الطويل العرضي 16:9 (1920x1080) مع الحفاظ على التناسب"""
    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = VIDEO_W / VIDEO_H
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) > 0.25:
        # إذا كانت الصورة طولية، نصنع خلفية ضبابية سينمائية 1920x1080 ونضع الصورة في المنتصف
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
                    print(f"✨ Generated 16:9 image for Scene {scene_num} via {space_name}!", flush=True)
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


def animate_scene_smoothly(index, start_img, next_img, motion_prompt, out_raw_video):
    full_motion = f"{motion_prompt}, smooth continuous 3D cinematic documentary animation, high quality, keep characters consistent"
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

    if next_img and os.path.exists(next_img):
        for pool_idx, tok in enumerate(all_pool[:4]):
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
            print(f"🎬 Animating Scene {index + 1} via ({wan_space} - {label})...", flush=True)
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


def generate_raw_voice_for_scene(seg_idx, scene):
    text = scene["narration"]
    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=-4%",
                "--text", text, "--write-media", raw_mp3
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 1000:
                voice_ok = True
                break
        except Exception:
            time.sleep(0.5)

    if not voice_ok:
        encoded = urllib.parse.quote(text)
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en&q={encoded}", timeout=25)
        with open(raw_mp3, "wb") as f:
            f.write(r.content)

    warm_eq = "highpass=f=75,equalizer=f=180:width_type=o:width=1.5:g=2.6,equalizer=f=3600:width_type=o:width=2.0:g=1.8"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_mp3,
        "-af", (
            f"silenceremove=start_periods=1:start_silence=0.03:start_threshold=-42dB,"
            f"areverse,silenceremove=start_periods=1:start_silence=0.05:start_threshold=-42dB,areverse,"
            f"{warm_eq}"
        ),
        "-ar", "44100", "-ac", "2", trimmed_voice
    ], check=True)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", trimmed_voice
    ], capture_output=True, text=True, check=True)
    v_dur = float(probe.stdout.strip() or "16.0")
    return trimmed_voice, v_dur


def finalize_scene_audio_exact(seg_idx, scene, trimmed_voice, raw_v_dur, exact_target_dur, out_wav):
    """
    ضبط طول الصوت والمؤثرات الصوتية لكل مشهد ليطابق المدة المحسوبة بالمللي ثانية
    بحيث يكون إجمالي الفيديو 275.00 ثانية (4 دقائق و35 ثانية بالضبط)!
    """
    sfx_key = scene["sfx"]
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"
    sfx_url, sfx_vol = SFX_LIBRARY.get(sfx_key, SFX_LIBRARY["waves"])

    # إذا كان صوت المشهد أطول من المدة المخصصة له، نسرعه بنسبة طفيفة جداً، وإذا كان أقصر نترك وقفة درامية طبيعية
    if raw_v_dur > exact_target_dur - 0.35:
        tempo = min(max(raw_v_dur / (exact_target_dur - 0.35), 0.90), 1.25)
        voice_filter = f"atempo={round(tempo, 4)},adelay=180|180,volume=1.35"
    else:
        voice_filter = "adelay=250|250,volume=1.35"

    try:
        r = requests.get(sfx_url, timeout=15)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={exact_target_dur}",
                "-i", sfx_ogg,
                "-i", trimmed_voice,
                "-filter_complex",
                f"[1:a]atrim=0:{min(exact_target_dur, 3.0)},afade=t=in:d=0.1,afade=t=out:st={max(min(exact_target_dur, 3.0) - 0.6, 0.2)}:d=0.6,volume={sfx_vol}[s];"
                f"[2:a]{voice_filter}[v];"
                f"[0:a][s][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(exact_target_dur), "-ar", "44100", "-ac", "2", out_wav
            ], check=True)
            return
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={exact_target_dur}",
        "-i", trimmed_voice,
        "-filter_complex",
        f"[1:a]{voice_filter}[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(exact_target_dur), "-ar", "44100", "-ac", "2", out_wav
    ], check=True)


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


def build_scene_clip(index, scene, exact_duration, audio_file, all_scene_imgs):
    narration = scene["narration"]
    start_img = all_scene_imgs[index]
    next_img = all_scene_imgs[index + 1] if index + 1 < len(all_scene_imgs) else None

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(round(exact_duration * fps))

    ai_animated = animate_scene_smoothly(index, start_img, next_img, scene["motion_prompt"], raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_video
        ], capture_output=True, text=True, check=True)
        raw_vid_dur = max(float(v_probe.stdout.strip() or "3.0"), 1.0)
        stretch_factor = round((exact_duration + 0.25) / raw_vid_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_video,
            "-vf", (
                f"setpts={stretch_factor}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=3,"
                f"scale=2112:1188:force_original_aspect_ratio=increase,crop=2112:1188,"
                f"crop={VIDEO_W}:{VIDEO_H}:'(iw-{VIDEO_W})/2 - 35*(t/{exact_duration})':'(ih-{VIDEO_H})/2 - 20*(t/{exact_duration})',"
                f"cas=0.65,setsar=1,format=yuv420p"
            ),
            "-t", str(exact_duration), "-r", str(fps),
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
            "-t", str(exact_duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    clean_words = re.sub(r'["\'«»*():;,.?!—-]', '', narration).split()
    phrases = [" ".join(clean_words[i:i + 5]) for i in range(0, len(clean_words), 5)] or ["..."]
    step_dur = exact_duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"
    for p_idx, phrase in enumerate(phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_widescreen_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-t", str(exact_duration), "-i", png_file])
        start_t = round(p_idx * step_dur, 2)
        end_t = round((p_idx + 1) * step_dur, 2)
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:shortest=1:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    # انتقال ناعم ومستقل داخل كل مشهد (يمنع مشكلة التهنيج في المشاهد الأخيرة 100%)
    fade_out_st = max(round(exact_duration - 0.25, 2), 0.5)
    filter_parts.append(
        f"{last_stream}fade=t=in:st=0:d=0.22,fade=t=out:st={fade_out_st}:d=0.25,format=yuv420p[vout]"
    )

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs_cmd,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "1:a",
        "-t", str(exact_duration),
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        video_file
    ], check=True)
    return video_file


def upload_long_video_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    # بدون كلمة #shorts نهائياً حتى يحتسبه يوتيوب كفيديو طويل في شريط الـ Watch Hours!
    clean_title = title[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": (
                f"{title}\n\n"
                "The full documentary story of the 1962 Alcatraz prison escape by Frank Morris, John Anglin, and Clarence Anglin.\n"
                "#history #documentary #alcatraz #mystery #truecrime"
            ),
            "tags": ["alcatraz escape", "1962 alcatraz", "history documentary", "frank morris", "mystery", "how they escaped"],
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
    title = "How 3 Men Escaped the Most Impossible Prison on Earth Using Spoons & Raincoats"
    uploaded_map = discover_uploaded_images_map()
    print(f"📸 Uploaded Gemini images found in 'images/': {len(uploaded_map)} ({sorted(uploaded_map.keys())})", flush=True)

    # 1. تجهيز جميع الصور الـ 15 بمقاس 16:9 العرضي
    all_scene_imgs = []
    for idx, scene in enumerate(ALCATRAZ_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_map)
        all_scene_imgs.append(img_file)

    # 2. توليد الصوت الخام لجميع المشاهد الـ 15 وحساب التوزيع الزمني الدقيق ليصبح الإجمالي 275.0 ثانية (4:35) بالضبط!
    print("🎙️ Generating English Documentary Voiceover & calibrating exact 04:35 (275.0s) timeline...", flush=True)
    trimmed_voices = []
    raw_durs = []
    for idx, scene in enumerate(ALCATRAZ_SCENES):
        t_wav, r_dur = generate_raw_voice_for_scene(idx, scene)
        trimmed_voices.append(t_wav)
        raw_durs.append(r_dur)

    total_raw = sum(raw_durs)
    exact_durations = []
    running_sum = 0.0
    for idx, r_dur in enumerate(raw_durs):
        if idx < len(raw_durs) - 1:
            scaled = round((r_dur / total_raw) * TARGET_TOTAL_VIDEO_SECONDS, 2)
            exact_durations.append(scaled)
            running_sum += scaled
        else:
            # المشهد الأخير يأخذ الباقي بالمللي ثانية ليصبح المجموع 275.00 ثانية بالضبط
            last_dur = round(TARGET_TOTAL_VIDEO_SECONDS - running_sum, 2)
            exact_durations.append(last_dur)

    print(f"⏱️ Calibrated Scene Durations Sum: {round(sum(exact_durations), 2)}s (04:35 Exact)!", flush=True)

    # 3. إنتاج المشاهد الـ 15 بدون أي تجميد
    scene_videos = []
    for idx, scene in enumerate(ALCATRAZ_SCENES):
        exact_dur = exact_durations[idx]
        audio_wav = f"scene_audio_{idx}.wav"
        finalize_scene_audio_exact(idx, scene, trimmed_voices[idx], raw_durs[idx], exact_dur, audio_wav)
        print(f"--- Animating & Syncing Scene {idx + 1}/15 (Target: {exact_dur}s) ---", flush=True)
        clip = build_scene_clip(idx, scene, exact_dur, audio_wav, all_scene_imgs)
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_long.mp4"
    final_video = "final_long_04_35.mp4"

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    # ضبط الخلفية الصوتية الوثائقية وقفل الطول النهائي على 275.0 ثانية (4 دقائق و35 ثانية بالضبط)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.005",
        "-filter_complex",
        f"[1:a]lowpass=f=240[bg];[0:a]apad=whole_dur={TARGET_TOTAL_VIDEO_SECONDS},volume=1.15[fg];"
        f"[fg][bg]amix=inputs=2:duration=first:dropout_transition=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-t", str(TARGET_TOTAL_VIDEO_SECONDS),
        "-vf", f"scale={VIDEO_W}:{VIDEO_H},setsar=1,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
        "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
        "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
    ], check=True)

    print("🚀 Publishing 04:35 Long-Form Video to YouTube...", flush=True)
    for token in YT_REFRESH_TOKENS:
        try:
            upload_long_video_to_youtube(final_video, title, token)
        except Exception as e:
            print(f"[YouTube Error] {e}", flush=True)


assemble_and_publish()
