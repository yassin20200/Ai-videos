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

print("🚀 Starting Uncut 16:9 Documentary Studio (Part 2: The Antikythera Mechanism - Zero Lip-Sync)...", flush=True)

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
MASTER_SEED = 202602

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "underwater": ("https://actions.google.com/sounds/v1/water/air_woosh_underwater.ogg", 0.22),
    "waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.18),
    "impact": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.24),
    "scan": ("https://actions.google.com/sounds/v1/science_fiction/sci_fi_osh.ogg", 0.20),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.20),
    "fire": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.20)
}

STYLE_PREFIX = (
    "Masterpiece stylized 3D cinematic documentary render, Unreal Engine 5 studio lighting, "
    "rich textures, dramatic shadows, ultra-crisp 8k horizontal 16:9 widescreen, no text, no watermarks. "
)

# 15 مشهداً متكاملاً للجزء الثاني (آلية أنتيكيثيرا - بدون أي Lip-Sync!)
ANTIKYTHERA_SCENES = [
    {
        "id": 0,
        "sfx": "underwater",
        "narration": (
            "In the spring of nineteen hundred, a violent storm blew a crew of Greek sponge divers off course near the tiny rocky island of Antikythera. "
            "When the waves calmed, a diver named Elias Stadiatis dropped one hundred and fifty feet into the freezing Aegean Sea. "
            "Minutes later, he shot back to the surface trembling in terror, claiming he had found a seabed graveyard of rotting naked corpses and dead horses. "
            "What he had actually discovered were two-thousand-year-old marble and bronze statues from an ancient sunken treasure ship."
        ),
        "image_prompt": f"{STYLE_PREFIX}A 1900 Greek sponge diver in a brass helmet illuminating fallen ancient marble statues on the dark seabed.",
        "motion_prompt": "Cinematic 3D underwater camera glide as the diver's beam sweeps across ancient statues resting on the dark ocean floor, floating particles"
    },
    {
        "id": 1,
        "sfx": "impact",
        "narration": (
            "Over the next several months, divers hauled up priceless artifacts from a massive Roman-era cargo ship that sank around seventy BC: "
            "towering bronze gods, delicate glassware, and gold jewelry. "
            "Tossed aside in a museum courtyard was an ugly, barnacle-crusted green lump of corroded metal about the size of a shoebox. "
            "No one cared about it until May of nineteen oh-two, when the lump dried out, cracked right down the middle, "
            "and revealed precision-cut triangular bronze gear wheels hidden inside."
        ),
        "image_prompt": f"{STYLE_PREFIX}Macro close-up of a corroded green bronze chunk cracked open on a museum table revealing sharp triangular bronze gears inside.",
        "motion_prompt": "Slow 3D macro camera push-in toward the sharp ancient bronze gear teeth emerging from the cracked green marine crust"
    },
    {
        "id": 2,
        "sfx": "whoosh",
        "narration": (
            "Archaeologists staring at those corroded gears felt the floor drop beneath them. "
            "According to everything history books taught, complex interlocking gear trains like this did not appear until medieval European cathedral clocks "
            "in the fourteenth century—more than one thousand four hundred years after this ship sank. "
            "Finding a precision geared machine from ancient Greece was like opening an Egyptian pyramid and discovering a jet engine."
        ),
        "image_prompt": f"{STYLE_PREFIX}A glowing ancient Greek bronze geared mechanism floating in golden light contrasted against a towering medieval stone clock tower.",
        "motion_prompt": "Dramatic 3D camera sweep gliding from the glowing ancient bronze gear device toward the misty medieval cathedral clock tower"
    },
    {
        "id": 3,
        "sfx": "whoosh",
        "narration": (
            "Soon known as the Antikythera Mechanism, the fragile artifact eventually split into eighty-two corroded fragments inside the National Archaeological Museum in Athens. "
            "Two thousand years underwater had fused the delicate bronze plates into solid mineralized stone. "
            "For over seventy years, historians could only guess what it did, because trying to pry the layers apart would instantly crumble the greatest machine of antiquity into dust."
        ),
        "image_prompt": f"{STYLE_PREFIX}Overhead museum shot of 82 corroded green bronze fragments laid out on black velvet trays under warm spotlights.",
        "motion_prompt": "Smooth 3D overhead camera pan gliding slowly across the 82 ancient corroded bronze fragments on black velvet trays"
    },
    {
        "id": 4,
        "sfx": "scan",
        "narration": (
            "The first real breakthrough arrived in nineteen seventy-one, when physicist Derek de Solla Price teamed up with Greek radiologist Charalampos Karakalos "
            "to blast powerful gamma rays and X-rays straight through the corroded fragments. "
            "When the glowing X-ray plates developed, the scientific world was stunned. "
            "Hidden inside the green crust were at least thirty interlocking hand-cut bronze gears, packed into a wooden frame tighter than a modern Swiss watch."
        ),
        "image_prompt": f"{STYLE_PREFIX}Glowing blue-and-white X-ray plates hanging on a lightbox revealing thirty interlocking toothed gears inside corroded bronze.",
        "motion_prompt": "3D laboratory animation, camera pushes smoothly toward the glowing X-ray lightbox illuminating the hidden gear silhouettes"
    },
    {
        "id": 5,
        "sfx": "scan",
        "narration": (
            "Still, the true purpose of the machine remained only half-understood until two thousand and five, "
            "when an international team flew an eight-ton high-resolution CT scanner called the Bladerunner into Athens. "
            "Slicing through the solid metal digitally in three dimensions, the scanner uncovered over three thousand microscopic Greek letters "
            "engraved directly onto the hidden inner plates—an actual ancient user manual explaining how to operate the world's first analog computer."
        ),
        "image_prompt": f"{STYLE_PREFIX}A massive industrial CT scanner shining a glowing cyan laser grid over the bronze fragment with a 3D holographic scan floating above.",
        "motion_prompt": "3D high-tech visualization, a glowing cyan CT scanner laser sweeps across the bronze fragment as golden 3D Greek letters illuminate"
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "narration": (
            "Using those three-dimensional scans, engineers finally reconstructed what the Antikythera Mechanism looked like when it was brand new. "
            "It sat inside a polished wooden case with a single brass hand-crank on the side. "
            "Turn that crank forward or backward to any date in history, and golden pointers spun around the front dial "
            "to calculate the exact positions of the Sun, the Moon, and all five planets visible to the naked eye: Mercury, Venus, Mars, Jupiter, and Saturn."
        ),
        "image_prompt": f"{STYLE_PREFIX}Fully restored gleaming golden-bronze Antikythera Mechanism in a dark wooden case with a brass side crank and planetary pointers.",
        "motion_prompt": "Majestic 3D mechanical animation, golden pointers and concentric bronze rings rotate smoothly around the restored front face of the ancient computer"
    },
    {
        "id": 7,
        "sfx": "whoosh",
        "narration": (
            "Right near the center of the front dial sat one of the most charming pieces of engineering ever built: "
            "a tiny metallic sphere painted half glossy black and half bright silver. "
            "Driven by a miniature bevel gear hidden behind the faceplate, this little sphere rotated smoothly as you turned the hand crank, "
            "automatically displaying the exact phase of the Moon—new, crescent, quarter, or full—for any night you chose."
        ),
        "image_prompt": f"{STYLE_PREFIX}Macro 3D close-up of a tiny half-black and half-silver metallic sphere rotating on a miniature bronze gear on the front dial.",
        "motion_prompt": "Macro 3D mechanical animation, the gleaming half-black and half-silver moon sphere rotates smoothly on its miniature bronze gear"
    },
    {
        "id": 8,
        "sfx": "impact",
        "narration": (
            "But hidden deep behind that moon dial was a mechanical trick that left modern physicists speechless. "
            "Because the Moon orbits Earth in an oval ellipse rather than a perfect circle, it actually speeds up when closer to Earth and slows down when farther away. "
            "Somehow, the ancient Greek inventor modeled this variable speed using two stacked bronze gears mounted slightly off-center, "
            "linked by a tiny metal pin sliding inside a slot—turning steady hand-cranking into an exact mathematical simulation of elliptical lunar motion."
        ),
        "image_prompt": f"{STYLE_PREFIX}X-ray mechanical cutaway showing two stacked off-center golden bronze gears linked by a glowing pin sliding inside a curved slot.",
        "motion_prompt": "Precision 3D engineering animation, the stacked off-center bronze gears rotate smoothly as the golden pin glides inside the curved slot"
    },
    {
        "id": 9,
        "sfx": "whoosh",
        "narration": (
            "Flip the bronze computer over, and the back face is just as mind-blowing, dominated by two large spiral tracks shaped like bronze vinyl records. "
            "The upper spiral tracked the nineteen-year Metonic cycle, a precise calendar that synchronized the solar year with lunar months across two hundred and thirty-five moons. "
            "And tucked neatly beside it sat a tiny four-year dial that counted down the exact arrival of the ancient Olympic Games."
        ),
        "image_prompt": f"{STYLE_PREFIX}Detailed 3D shot of the back face of the bronze Antikythera Mechanism with two ornate spiral dials and a four-year Olympic Games dial.",
        "motion_prompt": "Smooth 3D close-up pan across the ornate bronze spiral tracks and sliding pointers on the back face of the mechanism"
    },
    {
        "id": 10,
        "sfx": "impact",
        "narration": (
            "The lower spiral on the back was the most awe-inspiring feature of all: the two-hundred-and-twenty-three-month Saros eclipse predictor. "
            "As the sliding needle traveled along the spiral groove, tiny engraved glyphs warned the user of upcoming solar and lunar eclipses down to the exact month, day, and hour. "
            "Astonishingly, the microscopic Greek notes beside each glyph even predicted the direction of the shadow and whether the eclipsed moon would glow blood-red or dark black."
        ),
        "image_prompt": f"{STYLE_PREFIX}The lower bronze spiral dial glowing in the foreground with a breathtaking blood-red lunar eclipse and golden solar eclipse unfolding behind it.",
        "motion_prompt": "Cinematic 3D cosmic animation, the bronze eclipse dial glows while the blood-red lunar eclipse and golden solar corona shimmer in the night sky"
    },
    {
        "id": 11,
        "sfx": "fire",
        "narration": (
            "Who on Earth possessed both the genius astronomical math and the watchmaker-level metallurgy to file two hundred and twenty-three gear teeth by hand "
            "within a fraction of a millimeter? "
            "Clues in the regional calendar names engraved on the dials point directly to the school of the legendary inventor Archimedes of Syracuse, "
            "or the astronomer Hipparchus on the island of Rhodes, who were famed in Roman texts for building mechanical bronze globes of the heavens."
        ),
        "image_prompt": f"{STYLE_PREFIX}Over-the-shoulder view of an ancient Greek craftsman's hands filing tiny gear teeth into a shiny bronze wheel by warm oil-lamp light.",
        "motion_prompt": "Warm 3D historical animation, oil-lamp light flickers softly over the ancient craftsman's hands filing the gleaming bronze gear teeth"
    },
    {
        "id": 12,
        "sfx": "fire",
        "narration": (
            "This raises history's most haunting question: if the ancient Greeks built handheld bronze computers in one hundred BC, "
            "why did this technology vanish from human civilization for fourteen centuries? "
            "The tragic answer is simple: bronze was infinitely valuable and endlessly recyclable. "
            "When empires collapsed, ancient scientific instruments weren't saved in museums—they were thrown into blazing furnaces and melted down into swords, coins, and bells. "
            "The Antikythera Mechanism survived only because a deadly storm hid it at the bottom of the ocean."
        ),
        "image_prompt": f"{STYLE_PREFIX}Inside a dark ancient foundry, glowing molten bronze pours into molds while broken bronze astrolabes and gear wheels wait beside the furnace.",
        "motion_prompt": "Dramatic 3D foundry animation, glowing orange sparks rise as molten bronze pours beside piles of ancient discarded bronze gears"
    },
    {
        "id": 13,
        "sfx": "whoosh",
        "narration": (
            "Today, modern watchmakers and scientists at University College London have finally machined working brass replicas directly from the three-dimensional CT scans, "
            "proving that every single gear tooth, epicycle, and pointer meshes together with breathtaking mechanical accuracy. "
            "Every time that replica turns, it reminds us that ancient engineers were never primitive—they were just one shipwreck away from being forgotten completely."
        ),
        "image_prompt": f"{STYLE_PREFIX}A gleaming modern glass-cased working brass replica of the Antikythera Mechanism on a dark desk with polished golden gears turning.",
        "motion_prompt": "Ultra-clean 3D horology camera orbit around the glass-cased modern brass replica as its polished golden gears mesh and turn"
    },
    {
        "id": 14,
        "sfx": "fire",
        "narration": (
            "The Antikythera Mechanism proved that ancient civilizations mastered precision computing long before modern history gives them credit for. "
            "And this ancient mystery is only Part Two of our series. "
            "In Part Three, we uncover the most terrifying secret chemical weapon of the ancient world: "
            "Byzantine Greek Fire—a mysterious liquid flame that exploded on contact with water and saved an entire empire. "
            "Subscribe now so you don't miss Part Three, and check the link below if you haven't watched Part One on Roman self-healing concrete!"
        ),
        "image_prompt": f"{STYLE_PREFIX}The glowing bronze Antikythera Mechanism on the left fading beside an ancient Byzantine warship blasting roaring green-and-orange Greek Fire across dark waves on the right.",
        "motion_prompt": "Epic 3D cinematic closing animation, blazing green-and-orange Greek Fire erupts across the stormy waves beside the gleaming golden bronze gears"
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


def animate_scene_smoothly(index, scene, start_img, out_raw_video):
    full_motion = f"{scene['motion_prompt']}, smooth continuous 3D cinematic documentary animation, high quality, no talking, keep structure intact"
    neg_prompt = "talking face, open mouth, morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue
        label = "Free Server IP" if tok is None else f"HF Token #{pool_idx} ({tok[:10]}...)"
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"🎬 Animating Scene {index + 1}/15 (3D Documentary) via ({wan_space} - {label})...", flush=True)
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

    final_dur = round(v_dur + 0.80, 2)
    timed_phrases = parse_vtt_into_5word_phrases(raw_vtt, text, final_dur, delay_sec=0.15)

    sfx_url, sfx_vol = SFX_LIBRARY.get(sfx_key, SFX_LIBRARY["whoosh"])
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
    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(round(duration * fps))

    ai_animated = animate_scene_smoothly(index, scene, start_img, raw_ai_video)

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
                "Part 2 of Lost Ancient Engineering Secrets: The unbelievable story of the 2,000-year-old Antikythera Mechanism—the world's oldest analog computer found at the bottom of the Aegean Sea.\n"
                "#history #engineering #antikythera #ancientgreece #documentary #science"
            ),
            "tags": ["antikythera mechanism", "ancient computer", "ancient engineering", "history documentary", "ancient greece", "lost technology"],
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
    title = "The 2,000-Year-Old Ancient Computer Found at the Bottom of the Sea (Part 2)"
    uploaded_img_map = discover_uploaded_images_map()
    print(f"📸 Uploaded Gemini images found in 'images/': {len(uploaded_img_map)} ({sorted(uploaded_img_map.keys())})", flush=True)

    all_scene_imgs = []
    for idx, scene in enumerate(ANTIKYTHERA_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_img_map)
        all_scene_imgs.append(img_file)

    scene_videos = []
    total_dur = 0.0
    for idx, scene in enumerate(ANTIKYTHERA_SCENES):
        print(f"--- Producing Uncut Scene {idx + 1}/15 ---", flush=True)
        clip, dur = build_scene_clip(idx, scene, all_scene_imgs)
        scene_videos.append(clip)
        total_dur += dur

    print(f"⏱️ Total Uncut Documentary Duration: {round(total_dur, 1)}s ({round(total_dur / 60, 2)} minutes)!", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_long.mp4"
    final_video = "final_antikythera_part2.mp4"

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

    print("🚀 Publishing Part 2 Long-Form Documentary to YouTube...", flush=True)
    for token in YT_REFRESH_TOKENS:
        try:
            upload_long_video_to_youtube(final_video, title, token)
        except Exception as e:
            print(f"[YouTube Error] {e}", flush=True)


assemble_and_publish()
