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

print("🚀 Starting Smooth English Historical Shorts Studio (The 1859 Pig War)...", flush=True)

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
MASTER_SEED = 185901

os.environ.pop("HF_TOKEN", None)
EXHAUSTED_ZEROGPU_TOKENS = set()

SFX_LIBRARY = {
    "drums": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.30),
    "waves": ("https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg", 0.22),
    "pig": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.28),
    "shot": ("https://actions.google.com/sounds/v1/impacts/crash.ogg", 0.32),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.26),
    "cheer": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.26)
}

STYLE_PREFIX = (
    "Masterpiece stylized 3D cinematic historical animation render, Unreal Engine 5 & Pixar-grade rich textures, "
    "dramatic natural lighting, expressive 3D characters, 8k vertical 9:16, no text, no watermarks. "
)

PIG_WAR_SCENES = [
    {
        "id": 0,
        "sfx": "drums",
        "narration": "In 1859, the United States and the British Empire nearly went to full-scale war, over a single pig eating a potato.",
        "image_prompt": f"{STYLE_PREFIX}1859 American soldiers in blue uniforms and British soldiers in red coats aiming cannons at each other on a green island with a black pig eating a potato in the middle.",
        "motion_prompt": "Smooth 3D cinematic camera push-in toward the black pig munching a potato between the two aiming armies, dramatic wind moving the grass"
    },
    {
        "id": 1,
        "sfx": "waves",
        "narration": "It all started on San Juan Island, a tiny piece of land claimed by both countries, where American settlers and British workers lived side by side.",
        "image_prompt": f"{STYLE_PREFIX}Wide 3D shot of San Juan Island in 1859 with an American wooden cabin and US flag on one side and a British trading post with a Union Jack flag on the other.",
        "motion_prompt": "Smooth 3D aerial camera glide across the green island showing the American and British cabins with flags waving in the breeze"
    },
    {
        "id": 2,
        "sfx": "pig",
        "narration": "One morning, an American farmer named Lyman Cutlar walked out to his garden and found a giant black pig digging up his prized potatoes.",
        "image_prompt": f"{STYLE_PREFIX}An angry bearded 1859 American farmer in suspenders standing on his cabin porch staring at a large black pig digging up potatoes in his garden.",
        "motion_prompt": "3D character animation, the bearded farmer glares in disbelief as the black pig happily digs and munches potatoes in the garden"
    },
    {
        "id": 3,
        "sfx": "shot",
        "narration": "Furious because this wasn't the first time, Cutlar grabbed his rifle and shot the pig dead on the spot.",
        "image_prompt": f"{STYLE_PREFIX}The bearded 1859 American farmer in suspenders aiming an old musket rifle with a puff of white smoke by the wooden garden fence as birds fly up from the trees.",
        "motion_prompt": "3D cinematic animation, white smoke billows from the musket barrel as startled birds fly up from the pine trees"
    },
    {
        "id": 4,
        "sfx": "whoosh",
        "narration": "There was just one problem: the pig belonged to an Irishman working for the British, who demanded one hundred dollars and threatened to have Cutlar arrested.",
        "image_prompt": f"{STYLE_PREFIX}A furious British-Irish official in an 1859 tweed coat and top hat shouting and pointing his finger in the face of the bearded American farmer.",
        "motion_prompt": "3D expressive character animation, the official in the top hat gestures angrily while arguing with the stubborn bearded farmer"
    },
    {
        "id": 5,
        "sfx": "drums",
        "narration": "Terrified of British arrest, the American settlers called the U.S. Army, and Captain George Pickett landed on the island with sixty-six soldiers and cannons.",
        "image_prompt": f"{STYLE_PREFIX}1859 US Army soldiers in dark blue uniforms led by Captain George Pickett marching onto the rocky island beach pushing heavy brass cannons under an American flag.",
        "motion_prompt": "Epic 3D historical animation, American soldiers in blue uniforms march forward pushing brass cannons up the grassy beach as the flag waves"
    },
    {
        "id": 6,
        "sfx": "waves",
        "narration": "The British were outraged, so they sent five massive warships carrying seventy cannons and over two thousand Royal Marines to surround the beach.",
        "image_prompt": f"{STYLE_PREFIX}Five massive 1859 British Royal Navy wooden warships with open cannon ports and British flags anchored in the bay facing the tiny American camp on the hill.",
        "motion_prompt": "Epic 3D cinematic camera pan across the five massive British warships floating on the rippling ocean bay facing the island"
    },
    {
        "id": 7,
        "sfx": "drums",
        "narration": "For weeks, both armies stood nose to nose with loaded cannons, trading insults every day to trick the other side into firing the first shot.",
        "image_prompt": f"{STYLE_PREFIX}Close-up 3D standoff between 1859 American soldiers in blue and British Royal Marines in red coats standing nose-to-nose beside loaded brass cannons.",
        "motion_prompt": "Tense 3D cinematic camera movement between the glaring American and British soldiers standing beside loaded cannons"
    },
    {
        "id": 8,
        "sfx": "shot",
        "narration": "When the British Governor ordered his Admiral to attack the Americans, the stunned Admiral refused, shouting: I will not start a war between two great nations over a squabble about a pig!",
        "image_prompt": f"{STYLE_PREFIX}An older British Rear Admiral in a navy blue coat with gold epaulets slamming his hand on a map table aboard his warship, refusing an order to attack.",
        "motion_prompt": "3D dramatic character animation, the British Admiral shakes his head firmly over the map table aboard the wooden warship"
    },
    {
        "id": 9,
        "sfx": "whoosh",
        "narration": "Once news finally reached Washington and London, both governments were horrified and rushed diplomats to the island to calm everyone down.",
        "image_prompt": f"{STYLE_PREFIX}An elderly decorated American General stepping off a steamship onto the island pier, shaking hands with the British Admiral as soldiers lower their rifles.",
        "motion_prompt": "3D cinematic animation, the American General and British Admiral shake hands warmly on the pier as soldiers relax in the background"
    },
    {
        "id": 10,
        "sfx": "waves",
        "narration": "The two armies peacefully shared the island for twelve years, until an international judge finally awarded San Juan Island to the United States.",
        "image_prompt": f"{STYLE_PREFIX}1859 American soldiers in blue and British soldiers in red coats sitting peacefully together around a campfire on the island clinking mugs under both flags.",
        "motion_prompt": "Warm 3D animation, glowing campfire sparks rise as American and British soldiers laugh and clink mugs together peacefully"
    },
    {
        "id": 11,
        "sfx": "cheer",
        "narration": "And that is how the Pig War of 1859 ended in the history books, with zero human casualties, and one very unfortunate pig.",
        "image_prompt": f"{STYLE_PREFIX}A proud bronze statue of the chubby pig holding a potato on a stone pedestal in the sunny green island meadow with an American flag waving behind it.",
        "motion_prompt": "Smooth 3D camera pull-back revealing the bronze pig statue gleaming in the sunlight as the flag waves gently against the blue sky"
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

    if 0 in raw_num_map:
        return {k + 1: v for k, v in raw_num_map.items()}
    return raw_num_map


def save_clean_image(src_path, dst_file):
    img = Image.open(src_path).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
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
        save_clean_image(src, dst_jpg)
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
                    save_clean_image(img_path, dst_jpg)
                    print(f"✨ Generated fallback image for Scene {scene_num} via {space_name}!", flush=True)
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
    """
    الطريقة السلسة المتفق عليها:
    1. تحاول أولاً ربط صورة البداية بصورة النهاية عبر (multimodalart/wan-2-2-first-last-frame) لعمل انتقال متصل.
    2. أو تحرك اللقطة عبر (zerogpu-aoti/wan2-2-fp8da-aoti-faster) بانسيابية تامة.
    """
    full_motion = f"{motion_prompt}, smooth continuous 3D cinematic animation, high quality, keep characters consistent"
    neg_prompt = "morphing, deforming, melting, warping, blurry, low quality, worst quality, text, watermark, nsfw"
    all_pool = [None] + HF_TOKENS

    # 1. محاولة الربط الانتقالي First-Frame to Last-Frame إن توفرت الصورة التالية
    if next_img and os.path.exists(next_img):
        for pool_idx, tok in enumerate(all_pool[:5]):
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

    # 2. التحريك السينمائي المستمر عبر Wan 2.2 Faster
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
                duration_seconds=3.0,
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
                out = ps.call("/generate_video", [up_img, full_motion, 5, neg_prompt, 3.0, 1.1, 1.1, MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 Scene {index + 1} animated via {wan_space} Pinned ({label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    EXHAUSTED_ZEROGPU_TOKENS.add(tok_key)
                    continue

    return False


def build_segment_audio(seg_idx, scene, out_wav):
    text = scene["narration"]
    sfx_key = scene["sfx"]

    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=+5%",
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

    warm_eq = "highpass=f=75,equalizer=f=180:width_type=o:width=1.5:g=2.5,equalizer=f=3600:width_type=o:width=2.0:g=1.8"
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
    v_dur = float(probe.stdout.strip() or "4.5")
    final_dur = round(v_dur + 0.18, 2)

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
                "-i", trimmed_voice,
                "-filter_complex",
                f"[1:a]atrim=0:{min(final_dur, 2.0)},afade=t=in:d=0.05,afade=t=out:st={max(min(final_dur, 2.0) - 0.35, 0.1)}:d=0.35,volume={sfx_vol}[s];"
                f"[2:a]adelay=40|40,volume=1.35[v];"
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
        "[1:a]adelay=40|40,volume=1.35[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", str(final_dur), "-ar", "44100", "-ac", "2", out_wav
    ], check=True)
    return final_dur


def render_english_subtitle_png(phrase_text, png_path):
    font_file = ensure_english_font()
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_file, 52)

    words = phrase_text.upper().split()
    full_text = " ".join(words)
    bbox = draw.textbbox((0, 0), full_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x_pos = (1080 - w) // 2
    y_pos = 1520

    pad_x, pad_y = 36, 18
    draw.rounded_rectangle(
        [(x_pos - pad_x, y_pos - pad_y), (x_pos + w + pad_x, y_pos + h + pad_y + 12)],
        radius=24,
        fill=(10, 14, 22, 210),
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
    narration = scene["narration"]
    audio_file = f"scene_{index}.wav"
    duration = build_segment_audio(index, scene, audio_file)

    start_img = all_scene_imgs[index]
    next_img = all_scene_imgs[index + 1] if index + 1 < len(all_scene_imgs) else None

    raw_ai_video = f"raw_ai_{index}.mp4"
    base_video = f"base_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 10

    ai_animated = animate_scene_smoothly(index, start_img, next_img, scene["motion_prompt"], raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        v_probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", raw_ai_video
        ], capture_output=True, text=True, check=True)
        raw_vid_dur = max(float(v_probe.stdout.strip() or "3.0"), 1.0)
        stretch_factor = round((duration + 0.15) / raw_vid_dur, 3)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", raw_ai_video,
            "-vf", (
                f"setpts={stretch_factor}*PTS,"
                f"minterpolate=fps={fps}:mi_mode=blend,"
                f"tpad=stop_mode=clone:stop_duration=2,"
                f"scale=1220:2168:force_original_aspect_ratio=increase,crop=1220:2168,"
                f"crop=1080:1920:'(iw-1080)/2':'(ih-1920)/2 - 35*(t/{duration})',"
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
                f"d={total_frames}:s=1080x1920:fps={fps},cas=0.6,setsar=1,format=yuv420p"
            ),
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-an", base_video
        ], check=True)

    clean_words = re.sub(r'["\'«»*():;,.?!—-]', '', narration).split()
    phrases = [" ".join(clean_words[i:i + 3]) for i in range(0, len(clean_words), 3)] or ["..."]
    step_dur = duration / max(len(phrases), 1)

    inputs_cmd = ["-i", base_video, "-i", audio_file]
    filter_parts = []
    last_stream = "[0:v]"
    for p_idx, phrase in enumerate(phrases):
        png_file = f"sub_{index}_{p_idx}.png"
        render_english_subtitle_png(phrase, png_file)
        inputs_cmd.extend(["-loop", "1", "-t", str(duration), "-i", png_file])
        start_t = round(p_idx * step_dur, 2)
        end_t = round((p_idx + 1) * step_dur, 2)
        next_stream = f"[v{p_idx}]"
        inp_idx = p_idx + 2
        filter_parts.append(
            f"{last_stream}[{inp_idx}:v]overlay=0:0:shortest=1:enable='between(t,{start_t},{end_t})'{next_stream}"
        )
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


def merge_scenes_with_strong_transitions(scene_videos, scene_durations, out_merged_video):
    trans_duration = 0.24
    transition_types = ["fade", "smoothleft", "smoothright", "smoothup"]

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

    clean_title = f"{title[:68]} #history #shorts"[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": f"{title}\n\nThe true story of the 1859 Pig War between the United States and the British Empire.\n#history #weirdhistory #militaryhistory #facts #shorts",
            "tags": ["pig war", "history", "weird history", "1859", "us history", "british empire", "shorts"],
            "categoryId": "27"
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
            "description": f"{title} 🐖🔥\n\n#history #weirdhistory #facts #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] Published: {finish_res}", flush=True)


def assemble_and_publish():
    title = "How Two Nations Nearly Started War Over One Stolen Pig"
    uploaded_map = discover_uploaded_images_map()
    print(f"📸 Uploaded Gemini images found: {len(uploaded_map)} ({sorted(uploaded_map.keys())})", flush=True)

    # تجهيز جميع الصور الـ 12 أولاً حتى نتمكن من ربط كل صورة بالتي تليها (Start -> End Frame)
    all_scene_imgs = []
    for idx, scene in enumerate(PIG_WAR_SCENES):
        img_file = f"scene_img_{idx}.jpg"
        obtain_scene_image(idx, scene["image_prompt"], img_file, uploaded_map)
        all_scene_imgs.append(img_file)

    scene_videos = []
    scene_durations = []
    for idx, scene in enumerate(PIG_WAR_SCENES):
        print(f"--- Animating & Syncing Scene {idx + 1}/12 ---", flush=True)
        clip, dur = build_scene_clip(idx, scene, all_scene_imgs)
        scene_videos.append(clip)
        scene_durations.append(dur)

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    merge_scenes_with_strong_transitions(scene_videos, scene_durations, merged_video)

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
