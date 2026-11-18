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

print("🚀 Starting Lost Ancient Engineering Series Trailer Short (9:16 - Zero Lip-Sync - Uncut Audio)...", flush=True)

VIDEO_W, VIDEO_H = 1080, 1920  # Vertical 9:16 YouTube Shorts & Reels
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

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_BOLD_PATH = "Montserrat-ExtraBold.ttf"
MASTER_SEED = 202699

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "impact": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.28),
    "waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.20),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.24),
    "fire": ("https://actions.google.com/sounds/v1/weather/wind_blowing.ogg", 0.22),
    "clang": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.22)
}

STYLE_PREFIX = (
    "Masterpiece stylized 3D cinematic documentary render, Unreal Engine 5 studio lighting, "
    "rich textures, dramatic shadows, ultra-crisp 8k vertical 9:16, no text, no watermarks. "
)

TRAILER_SCENES = [
    {
        "id": 0,
        "sfx": "impact",
        "narration": "Modern engineers still can't recreate five ancient inventions, and one of them is already hiding under the ocean!",
        "image_prompt": f"{STYLE_PREFIX}Three mysterious glowing ancient artifacts on pedestals in a dark stone vault: a bronze gear computer, green liquid fire, and a Roman concrete column.",
        "motion_prompt": "Dramatic 3D camera push-in through floating dust particles toward the three glowing ancient artifacts in the dark vault"
    },
    {
        "id": 1,
        "sfx": "waves",
        "narration": "Part One: Why do modern concrete bridges crumble in fifty years, while two-thousand-year-old Roman harbors grow stronger?",
        "image_prompt": f"{STYLE_PREFIX}Split-level shot showing a cracked modern bridge above and an intact submerged ancient Roman concrete harbor in blue ocean waves below.",
        "motion_prompt": "Smooth 3D camera pan downward from the cracked bridge into the clear blue ocean waves surrounding the intact Roman pier"
    },
    {
        "id": 2,
        "sfx": "whoosh",
        "narration": "The Romans trapped tiny white calcium capsules inside hot-mixed mortar so their walls literally heal their own cracks.",
        "image_prompt": f"{STYLE_PREFIX}Macro 3D cutaway of blue seawater hitting a white calcium sphere inside a concrete crack and crystallizing to seal it shut.",
        "motion_prompt": "3D microscopic animation, sparkling white calcium crystals grow rapidly and seal the crack inside the stone wall"
    },
    {
        "id": 3,
        "sfx": "waves",
        "narration": "Part Two: Divers pulled a two-thousand-year-old bronze machine from a shipwreck, packed with precision gears.",
        "image_prompt": f"{STYLE_PREFIX}Underwater 3D shot of a diver flashlight illuminating the encrusted bronze Antikythera Mechanism resting on the sandy seabed.",
        "motion_prompt": "Underwater 3D camera glide as light beams sweep across the ancient bronze gears buried in the ocean floor"
    },
    {
        "id": 4,
        "sfx": "whoosh",
        "narration": "An ancient analog computer that predicted eclipses and planetary orbits a thousand years before mechanical clocks!",
        "image_prompt": f"{STYLE_PREFIX}Glowing 3D reconstruction of the bronze Antikythera Mechanism with interlocking golden cogwheels and celestial star rings.",
        "motion_prompt": "Cinematic 3D mechanical animation, dozens of intricate golden bronze gears rotate smoothly inside glowing star-chart rings"
    },
    {
        "id": 5,
        "sfx": "fire",
        "narration": "Part Three: The Byzantine Empire guarded a terrifying liquid weapon called Greek Fire...",
        "image_prompt": f"{STYLE_PREFIX}An ancient Byzantine warship shooting a roaring jet of blazing orange and green Greek Fire across dark stormy ocean waves.",
        "motion_prompt": "Epic 3D naval action animation, blazing orange and green flames roar out from the bronze dragon siphon of the warship"
    },
    {
        "id": 6,
        "sfx": "fire",
        "narration": "That burst into flames on top of water, couldn't be put out, and vanished into history forever.",
        "image_prompt": f"{STYLE_PREFIX}Intense close-up of fierce neon-green and orange flames burning violently on top of splashing dark ocean waves at night.",
        "motion_prompt": "3D elemental animation, emerald green and orange flames dance wildly across the rippling dark sea water"
    },
    {
        "id": 7,
        "sfx": "clang",
        "narration": "Part Four: Ancient blacksmiths forged Damascus blades with microscopic carbon nanotubes inside the steel!",
        "image_prompt": f"{STYLE_PREFIX}Macro 3D forge shot of a gleaming curved Damascus steel sword with swirling metallic patterns over red-hot embers and flying sparks.",
        "motion_prompt": "3D forge animation, bright golden sparks float upward past the shimmering swirling patterns on the Damascus sword blade"
    },
    {
        "id": 8,
        "sfx": "impact",
        "narration": "And Part Five: A two-thousand-year-old bronze dragon machine that detected earthquakes hundreds of miles away!",
        "image_prompt": f"{STYLE_PREFIX}Zhang Heng's ornate ancient Chinese bronze seismoscope urn with sculpted dragons dropping a metal ball toward a bronze toad below.",
        "motion_prompt": "3D dramatic animation, the shiny bronze sphere drops cleanly from the sculpted dragon jaw toward the bronze toad below"
    },
    {
        "id": 9,
        "sfx": "whoosh",
        "narration": "Part One on Roman self-healing concrete is out right now—tap the linked video below to watch the full story, and subscribe for Part Two!",
        "image_prompt": f"{STYLE_PREFIX}Inside the ancient Roman Pantheon as a golden sunbeam shines down through the dome oculus toward the bottom center of the frame.",
        "motion_prompt": "Majestic 3D camera push-in inside the Roman Pantheon as golden rays of light shimmer downward"
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


def save_clean_vertical_image(src_path, dst_file):
    img = Image.open(src_path).convert("RGB").resize((VIDEO_W, VIDEO_H), Image.Resampling.LANCZOS)
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
        save_clean_vertical_image(src, dst_jpg)
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


def animate_scene_cinematic(index, start_img, motion_prompt, out_raw_video):
    full_motion = f"{motion_prompt}, smooth continuous 3D cinematic animation, high quality, vivid lighting"
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

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


def vtt_time_to_seconds(t_str):
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return 0.0


def parse_vtt_into_3word_phrases(vtt_path, fallback_text, total_dur, delay_sec=0.08):
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

                chunks = [" ".join(clean_words[i:i + 3]) for i in range(0, len(clean_words), 3)]
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
    chunks = [" ".join(clean_words[i:i + 3]) for i in range(0, len(clean_words), 3)] or ["..."]
    step = total_dur / len(chunks)
    return [(ch, round(idx * step, 2), round((idx + 1) * step, 2)) for idx, ch in enumerate(chunks)]


def build_uncut_short_audio(seg_idx, scene, out_wav):
    """
    صوت واضح وسريع ومشوق للشورت بدون أي قص في نهاية الكلمات (Zero Truncation)
    """
    text = scene["narration"]
    sfx_key = scene["sfx"]

    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    raw_vtt = f"seg_sub_{seg_idx}.vtt"
    clean_voice_wav = f"seg_clean_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=+6%",
                "--text", text,
                "--write-media", raw_mp3,
                "--write-subtitles", raw_vtt
            ], check=True, timeout=30, stderr=subprocess.DEVNULL)
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
    v_dur = float(probe.stdout.strip() or "4.5")

    # إضافة 0.35 ثانية بعد انتهاء الصوت لضمان وضوح آخر كلمة وعدم قطعها مع إيقاع سريع للشورت
    final_dur = round(v_dur + 0.35, 2)
    timed_phrases = parse_vtt_into_3word_phrases(raw_vtt, text, final_dur, delay_sec=0.08)

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
                f"[1:a]atrim=0:{min(final_dur, 1.8)},afade=t=in:d=0.05,afade=t=out:st={max(min(final_dur, 1.8) - 0.35, 0.1)}:d=0.35,volume={sfx_vol}[s];"
                f"[2:a]adelay=80|80,apad=pad_dur=0.25,volume=1.40[v];"
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
        "[1:a]adelay=80|80,apad=pad_dur=0.25,volume=1.40[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
    ], check=True)
    return final_dur, timed_phrases


def render_short_subtitle_png(phrase_text, png_path):
    font_file = ensure_english_font()
    img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 52)

    words = phrase_text.upper().split()
    full_text = " ".join(words)
    bbox = draw.textbbox((0, 0), full_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (VIDEO_W - w) // 2
    y_pos = 1480

    pad_x, pad_y = 34, 18
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 12)],
        radius=24,
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
    duration, timed_phrases = build_uncut_short_audio(index, scene, audio_file)

    start_img = all_scene_imgs[index]
    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(round(duration * fps))

    ai_animated = animate_scene_cinematic(index, start_img, scene["motion_prompt"], raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_video
        ], capture_output=True, text=True, check=True)
        raw_vid_dur = max(float(v_probe.stdout.strip() or "3.2"), 1.0)
        stretch_factor = round((duration + 0.15) / raw_vid_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_video,
            "-vf", (
                f"setpts={stretch_factor}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=2,"
                f"scale=1220:2168:force_original_aspect_ratio=increase,crop=1220:2168,"
                f"crop={VIDEO_W}:{VIDEO_H}:'(iw-{VIDEO_W})/2':'(ih-{VIDEO_H})/2 - 35*(t/{duration})',"
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
                f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
                f"zoompan=z='min(zoom+0.0020,1.22)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
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
        render_short_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-t", str(duration), "-i", png_file])
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:shortest=1:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
        last_stream = next_stream

    # انتقال سريع وناعم (0.10 ثانية) مضمون 100% بدون أي تجميد في المشاهد الأخيرة!
    fade_out_st = max(round(duration - 0.10, 2), 0.3)
    filter_parts.append(
        f"{last_stream}fade=t=in:st=0:d=0.08,fade=t=out:st={fade_out_st}:d=0.10,format=yuv420p[vout]"
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


def upload_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    clean_title = f"{title[:72]} #shorts #history"[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": (
                f"{title}\n\n"
                "Watch Part 1 (Roman Self-Healing Concrete) linked right below this Short! 👇\n"
                "#shorts #history #engineering #science #ancientmysteries"
            ),
            "tags": ["ancient engineering", "lost inventions", "roman concrete", "antikythera mechanism", "greek fire", "shorts"],
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube Short] Uploaded successfully: https://youtu.be/{res['id']}", flush=True)


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
            "description": f"{title} 🔥\n\n#history #engineering #facts #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] Published: {finish_res}", flush=True)


def assemble_and_publish():
    title = "5 Ancient Inventions Modern Science Still Can't Recreate!"
    uploaded_img_map = discover_uploaded_images_map()
    print(f"📸 Uploaded Gemini images found in 'images/': {len(uploaded_img_map)} ({sorted(uploaded_img_map.keys())})", flush=True)

    all_scene_imgs = []
    for idx, scene in enumerate(TRAILER_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_img_map)
        all_scene_imgs.append(img_file)

    scene_videos = []
    total_dur = 0.0
    for idx, scene in enumerate(TRAILER_SCENES):
        print(f"--- Producing Short Scene {idx + 1}/10 ---", flush=True)
        clip, dur = build_scene_clip(idx, scene, all_scene_imgs)
        scene_videos.append(clip)
        total_dur += dur

    print(f"⏱️ Total Short Duration: {round(total_dur, 1)}s (Perfect Under-60s Trailer!)", flush=True)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_trailer_short.mp4"

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

    print("🚀 Publishing Trailer Short to YouTube & Facebook Reels...", flush=True)
    for token in YT_REFRESH_TOKENS:
        try:
            upload_to_youtube(final_video, title, token)
        except Exception as e:
            print(f"[YouTube Error] {e}", flush=True)

    if META_ACCESS_TOKEN:
        for page_id in FB_PAGE_IDS:
            try:
                upload_to_facebook_reels(final_video, title, page_id)
            except Exception as e:
                print(f"[Facebook Error] {e}", flush=True)


assemble_and_publish()
