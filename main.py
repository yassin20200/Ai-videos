import os
import re
import math
import json
import time
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

print("🚀 بدء تشغيل استوديو الإنتاج الثلاثي الأبعاد (3D AI + Programmatic HUD)...", flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
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
                break

    raise RuntimeError(f"Failed to generate 3D image for Stage {stage_idx + 1}")


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


def animate_3d_stage_with_wan(stage_idx, img_file, motion_prompt, out_raw_video):
    full_motion = f"{motion_prompt}, photorealistic 3D engineering cutaway animation, smooth fluid motion, high quality, keep structure intact"
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"

    all_pool = [None] + HF_TOKENS
    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"TOK_{tok[:12]}"
        if tok_key in EXHAUSTED_ZEROGPU_TOKENS:
            continue
        label = "Free Server IP" if tok is None else f"HF Token #{pool_idx} ({tok[:10]}...)"
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"🎬 Animating 3D Stage {stage_idx + 1} via ({wan_space} - {label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=5,
                negative_prompt=neg_prompt,
                duration_seconds=3.0,
                guidance_scale=1.1,
                guidance_scale_2=1.1,
                seed=MASTER_SEED + stage_idx,
                randomize_seed=False,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 Stage {stage_idx + 1} animated via {wan_space} ({label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                continue
            try:
                ps = PinnedSpace(wan_space, token=tok)
                up_img = ps.upload(img_file)
                out = ps.call("/generate_video", [up_img, full_motion, 5, neg_prompt, 3.0, 1.1, 1.1, MASTER_SEED + stage_idx, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 Stage {stage_idx + 1} animated via {wan_space} Pinned ({label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def build_segment_audio(seg_idx, segment, out_wav):
    text = segment["narration"]
    sfx_key = segment["sfx"]

    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=+8%",
                "--text", text, "--write-media", raw_mp3
            ], check=True, timeout=25, stderr=subprocess.DEVNULL)
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

    warm_eq = "highpass=f=80,equalizer=f=185:width_type=o:width=1.5:g=2.5,equalizer=f=3800:width_type=o:width=2.0:g=2.0"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_mp3,
        "-af", (
            f"silenceremove=start_periods=1:start_silence=0.02:start_threshold=-42dB,"
            f"areverse,silenceremove=start_periods=1:start_silence=0.04:start_threshold=-42dB,areverse,"
            f"{warm_eq}"
        ),
        "-ar", "44100", "-ac", "2", trimmed_voice
    ], check=True)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", trimmed_voice
    ], capture_output=True, text=True, check=True)
    v_dur = float(probe.stdout.strip() or "4.5")
    final_dur = round(v_dur + 0.16, 2)

    sfx_url, sfx_vol = SFX_LIBRARY.get(sfx_key, SFX_LIBRARY["pop"])
    try:
        r = requests.get(sfx_url, timeout=15)
        if r.ok and len(r.content) > 1000:
            with open(sfx_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
                "-i", sfx_ogg,
                "-i", trimmed_voice,
                "-filter_complex",
                f"[1:a]atrim=0:{min(final_dur, 2.0)},afade=t=in:d=0.04,afade=t=out:st={max(min(final_dur, 2.0) - 0.35, 0.1)}:d=0.35,volume={sfx_vol}[s];"
                f"[2:a]adelay=30|30,volume=1.35[v];"
                f"[0:a][s][v]amix=inputs=3:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
            ], check=True)
            return final_dur
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={final_dur}",
        "-i", trimmed_voice,
        "-filter_complex",
        "[1:a]adelay=30|30,volume=1.35[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
    ], check=True)
    return final_dur


def lerp(a, b, t):
    return a + (b - a) * t


class ProgrammaticHUDOverlay:
    def __init__(self, font_path):
        self.font_word = ImageFont.truetype(font_path, 78)
        self.font_label = ImageFont.truetype(font_path, 28)
        self.font_gauge_num = ImageFont.truetype(font_path, 52)
        self.font_gauge_sub = ImageFont.truetype(font_path, 26)
        self.font_card = ImageFont.truetype(font_path, 32)
        random.seed(42)
        self.confetti = [
            (
                random.uniform(40, 1040),
                random.uniform(-600, 1200),
                random.uniform(5, 10),
                random.choice([(255, 80, 80), (60, 180, 255), (255, 215, 40), (80, 230, 120), (200, 100, 255)])
            )
            for _ in range(90)
        ]

    def draw_callout_badge(self, draw, target_xy, box_xy, text, bg_color, progress):
        if progress < 0.08:
            return
        tx, ty = target_xy
        bx, by = box_xy
        bbox = draw.textbbox((0, 0), text, font=self.font_label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 22, 13
        bw = tw + pad_x * 2
        bh = th + pad_y * 2

        bx = max(bw // 2 + 24, min(1080 - bw // 2 - 24, int(bx)))
        by = max(bh // 2 + 120, min(1920 - bh // 2 - 120, int(by)))

        line_prog = min(1.0, (progress - 0.08) * 3.5)
        cur_bx = int(lerp(tx, bx, line_prog))
        cur_by = int(lerp(ty, by, line_prog))

        draw.line([(tx, ty), (cur_bx, cur_by)], fill=(255, 255, 255, 235), width=5)
        draw.line([(tx, ty), (cur_bx, cur_by)], fill=(30, 40, 50, 255), width=3)
        draw.ellipse([tx - 7, ty - 7, tx + 7, ty + 7], fill=(255, 255, 255, 255), outline=(30, 40, 50, 255), width=2)

        if line_prog >= 0.85:
            rect = [bx - bw // 2, by - bh // 2, bx + bw // 2, by + bh // 2]
            draw.rounded_rectangle(rect, radius=24, fill=(*bg_color, 235), outline=(255, 255, 255, 255), width=3)
            draw.text((bx - tw // 2, by - th // 2 - 2), text, font=self.font_label, fill=(255, 255, 255, 255))

    def draw_temp_gauge(self, draw, temp_c, label="CORE TEMPERATURE"):
        card = [250, 1490, 830, 1690]
        draw.rounded_rectangle(card, radius=28, fill=(248, 246, 238, 240), outline=(40, 50, 60, 255), width=5)

        bar_bg = [290, 1530, 570, 1582]
        draw.rounded_rectangle(bar_bg, radius=22, fill=(225, 225, 225, 255), outline=(55, 65, 75, 255), width=3)

        ratio = max(0.08, min(1.0, (temp_c - 150.0) / 1050.0))
        fill_w = int((570 - 290 - 8) * ratio)
        bar_color = (230, 55, 45, 255) if temp_c >= 700 else (45, 185, 85, 255)
        draw.rounded_rectangle([294, 1534, 294 + fill_w, 1578], radius=18, fill=bar_color)

        t_str = f"{int(temp_c)}°C"
        draw.text((592, 1524), t_str, font=self.font_gauge_num, fill=bar_color)

        bbox = draw.textbbox((0, 0), label, font=self.font_gauge_sub)
        lw = bbox[2] - bbox[0]
        draw.text((540 - lw // 2, 1616), label, font=self.font_gauge_sub, fill=(40, 50, 60, 255))

    def render_hud_on_frame(self, base_rgb_img, stage, prog, current_word):
        img = base_rgb_img.convert("RGBA")
        draw = ImageDraw.Draw(img, "RGBA")

        for c_item in stage.get("callouts", []):
            self.draw_callout_badge(draw, c_item["target"], c_item["box"], c_item["text"], c_item["color"], prog)

        g_mode = stage.get("gauge_mode")
        if g_mode == "cool_down":
            t_val = lerp(468, 1200, prog / 0.48) if prog < 0.48 else lerp(1200, 300, (prog - 0.48) / 0.52)
            self.draw_temp_gauge(draw, t_val, "CORE TEMPERATURE")
        elif g_mode == "river_70" and prog > 0.38:
            self.draw_temp_gauge(draw, 70, "RIVER WATER TEMP")
        elif g_mode == "overheat_1064":
            self.draw_temp_gauge(draw, lerp(745, 1064, min(prog * 1.6, 1.0)), "CORE TEMPERATURE")

        if stage.get("show_pellet_card"):
            c_box = [125, 1240, 955, 1690]
            draw.rounded_rectangle(c_box, radius=32, fill=(250, 246, 235, 238), outline=(40, 50, 60, 255), width=5)
            draw.rounded_rectangle([235, 1390, 302, 1478], radius=12, fill=(125, 135, 145, 255), outline=(40, 45, 50, 255), width=4)
            draw.ellipse([345, 1382, 405, 1438], fill=(235, 65, 55, 255), outline=(140, 30, 25, 255), width=3)
            draw.rounded_rectangle([340, 1418, 410, 1478], radius=18, fill=(235, 65, 55, 255), outline=(140, 30, 25, 255), width=3)
            draw.text((200, 1520), "1 FUEL PELLET", font=self.font_card, fill=(40, 45, 50, 255))
            draw.text((515, 1395), "=", font=self.font_word, fill=(235, 165, 40, 255))
            for cx_c, cy_c in [(690, 1455), (745, 1455), (800, 1455), (715, 1410), (770, 1410), (742, 1365)]:
                draw.regular_polygon((cx_c, cy_c, 32), n_sides=6, fill=(55, 60, 65, 255), outline=(25, 30, 35, 255))
            draw.text((645, 1520), "1 TON OF COAL", font=self.font_card, fill=(40, 45, 60, 255))

        if stage.get("show_confetti"):
            for c_x, c_y0, c_s, c_col in self.confetti:
                cy_now = (c_y0 + prog * 1050) % 1920
                cx_now = c_x + math.sin(prog * 15 + c_x) * 18
                draw.rectangle([cx_now - c_s, cy_now - c_s * 1.6, cx_now + c_s, cy_now + c_s * 1.6], fill=(*c_col, 255))

        if current_word:
            w_text = current_word.upper()
            bbox = draw.textbbox((0, 0), w_text, font=self.font_word)
            tw = bbox[2] - bbox[0]
            wx_pos = (1080 - tw) // 2
            wy_pos = 340

            for dx in (-5, -3, 0, 3, 5):
                for dy in (-5, -3, 0, 3, 5):
                    if dx != 0 or dy != 0:
                        draw.text((wx_pos + dx, wy_pos + dy), w_text, font=self.font_word, fill=(25, 35, 45, 255))
            draw.text((wx_pos, wy_pos), w_text, font=self.font_word, fill=(255, 255, 255, 255))

        return img.convert("RGB")


def pick_word_by_weighted_time(words, prog):
    weights = [max(len(w), 2) + 1.5 for w in words]
    total_w = sum(weights)
    target = prog * total_w
    acc = 0.0
    for idx, w_val in enumerate(weights):
        acc += w_val
        if target <= acc:
            return words[idx]
    return words[-1]


def build_stage_video_with_hud(stage_idx, stage, hud, out_stage_mp4):
    audio_wav = f"stage_{stage_idx}.wav"
    duration = build_segment_audio(stage_idx, stage, audio_wav)

    img_jpg = f"nuclear_3d_{stage_idx}.jpg"
    generate_3d_stage_image(stage_idx, stage["image_prompt"], img_jpg)

    raw_ai_mp4 = f"raw_wan_{stage_idx}.mp4"
    stretched_mp4 = f"stretched_{stage_idx}.mp4"
    fps = 30
    total_frames = max(int(round(duration * fps)), 1)

    animated = animate_3d_stage_with_wan(stage_idx, img_jpg, stage["motion_prompt"], raw_ai_mp4)
    if animated and os.path.exists(raw_ai_mp4):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_mp4
        ], capture_output=True, text=True, check=True)
        raw_dur = max(float(v_probe.stdout.strip() or "2.5"), 1.0)
        stretch = round((duration + 0.15) / raw_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_mp4,
            "-vf", (
                f"setpts={stretch}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=2,"
                f"scale=1220:2168:force_original_aspect_ratio=increase,crop=1220:2168,"
                f"crop=1080:1920:'(iw-1080)/2':'(ih-1920)/2 - 35*(t/{duration})',"
                f"cas=0.65,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "15", "-an", stretched_mp4
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_jpg,
            "-vf", (
                f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
                f"zoompan=z='min(zoom+0.0020,1.22)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={total_frames}:s=1080x1920:fps={fps},cas=0.6,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "15", "-an", stretched_mp4
        ], check=True)

    reader_proc = subprocess.Popen([
        "ffmpeg", "-loglevel", "error",
        "-i", stretched_mp4,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920", "-r", str(fps), "-"
    ], stdout=subprocess.PIPE)

    writer_proc = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1080x1920", "-pix_fmt", "rgb24", "-r", str(fps),
        "-i", "-",
        "-i", audio_wav,
        "-map", "0:v", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        out_stage_mp4
    ], stdin=subprocess.PIPE)

    frame_bytes_len = 1080 * 1920 * 3
    words = re.sub(r'[,.?!—-]', '', stage["narration"]).split() or [""]
    last_valid_img = Image.open(img_jpg).convert("RGB").resize((1080, 1920))

    for f_i in range(total_frames):
        raw_buf = reader_proc.stdout.read(frame_bytes_len)
        if len(raw_buf) == frame_bytes_len:
            base_frame = Image.frombytes("RGB", (1080, 1920), raw_buf)
            last_valid_img = base_frame
        else:
            base_frame = last_valid_img

        prog = f_i / max(total_frames - 1, 1)
        curr_word = pick_word_by_weighted_time(words, prog)
        composited = hud.render_hud_on_frame(base_frame, stage, prog, curr_word)
        writer_proc.stdin.write(composited.tobytes())

    reader_proc.stdout.close()
    writer_proc.stdin.close()
    reader_proc.wait()
    writer_proc.wait()
    return out_stage_mp4, duration


def merge_scenes_with_strong_transitions(scene_videos, scene_durations, out_merged_video):
    trans_duration = 0.25
    transition_types = ["smoothup", "smoothleft", "fade", "smoothdown", "circleopen", "smoothright"]

    inputs_cmd = []
    for v in scene_videos:
        inputs_cmd.extend(["-i", v])

    v_filters = []
    a_filters = []
    cumulative_offset = 0.0
    prev_v = "[0:v]"
    prev_a = "[0:a]"

    for i in range(1, len(scene_videos)):
        cumulative_offset += scene_durations[i - 1] - trans_duration
        offset_val = max(round(cumulative_offset, 2), 0.5)
        t_type = transition_types[(i - 1) % len(transition_types)]
        next_v = f"[vx{i}]" if i < len(scene_videos) - 1 else "[vfinal]"
        next_a = f"[ax{i}]" if i < len(scene_videos) - 1 else "[afinal]"

        v_filters.append(
            f"{prev_v}[{i}:v]xfade=transition={t_type}:duration={trans_duration}:offset={offset_val}{next_v}"
        )
        a_filters.append(
            f"{prev_a}[{i}:a]acrossfade=d={trans_duration}:c1=tri:c2=tri{next_a}"
        )
        prev_v = next_v
        prev_a = next_a

    full_filter = ";".join(v_filters + a_filters)
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            *inputs_cmd,
            "-filter_complex", full_filter,
            "-map", "[vfinal]", "-map", "[afinal]",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            out_merged_video
        ], check=True)
    except Exception:
        with open("inputs.txt", "w") as f:
            for v in scene_videos:
                f.write(f"file '{v}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", "inputs.txt", "-c", "copy", out_merged_video
        ], check=True)


def upload_to_youtube(video_path, title, refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)

    clean_title = f"{title[:65]} #nuclear #science #shorts"[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": f"{title}\n\n3D Cutaway Animated Explainer: How a Nuclear Power Plant Works.\n#engineering #science #howitworks #nuclearpower #shorts",
            "tags": ["nuclear power plant", "how it works", "engineering", "science", "3d animation", "shorts"],
            "categoryId": "28"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube] Uploaded successfully: https://youtu.be/{res['id']}", flush=True)


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
            "description": f"{title} ⚛️⚡\n\n#engineering #science #howitworks #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] Published: {finish_res}", flush=True)


def assemble_and_publish():
    title = "How a Nuclear Power Plant Works From the Inside!"
    font_path = ensure_english_font()
    hud = ProgrammaticHUDOverlay(font_path)

    print(f"🚀 Total HF Accounts Ready for 8K 3D Rendering & Animation: {len(HF_TOKENS)}", flush=True)
    stage_videos = []
    stage_durations = []

    for idx, stage in enumerate(NUCLEAR_PLANT_STAGES):
        print(f"--- Building 3D Stage {idx + 1}/12 + Programmatic HUD ---", flush=True)
        out_mp4 = f"stage_final_{idx}.mp4"
        clip, dur = build_stage_video_with_hud(idx, stage, hud, out_mp4)
        stage_videos.append(clip)
        stage_durations.append(dur)

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    merge_scenes_with_strong_transitions(stage_videos, stage_durations, merged_video)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", merged_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.005",
        "-filter_complex",
        "[1:a]lowpass=f=260[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-movflags", "+faststart", final_video
    ], check=True)

    print("🚀 Publishing to YouTube & Facebook Reels...", flush=True)
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
