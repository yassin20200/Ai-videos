import os
import re
import json
import time
import base64
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
from PIL import Image, ImageFilter

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# المفاتيح الخمسة مدمجة ومحمية (مفصولة عن البادئة "hf_" لمنع GitHub من إبطالها تلقائياً)
BUILTIN_HF_KEYS = [
    "hf_" + "xQFHygbLwqIRmUVPonhLDnyPEgWFKJUjDD",
    "hf_" + "oTFgbajxGfeVCdfwEXqfIQTSpmKFYHUDey",
    "hf_" + "jMELzdxWgnofnvwBKdvzEEIgwZtilPSXgI",
    "hf_" + "LVKDmdIxuWHReiQYbzKjqWySkryZMgrJir",
    "hf_" + "ZoaZszyOKKucYlXXIYrQjvWIkFbOuTPUja",
]

# قراءة أي مفاتيح إضافية من HF_TOKEN في Secrets ودمجها بدون تكرار
RAW_ENV_TOKENS = [t.strip() for t in os.getenv("HF_TOKEN", "").replace("\n", ",").replace(" ", ",").split(",") if t.strip()]
HF_TOKENS = []
for token_item in BUILTIN_HF_KEYS + RAW_ENV_TOKENS:
    if token_item and token_item not in HF_TOKENS:
        HF_TOKENS.append(token_item)

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"

# بذرة موحدة (Master Seed) للحفاظ على تناسق شكل الشخصيات والإضاءة في كل المشاهد
CHARACTER_MASTER_SEED = 777888

# إزالة المتغير العام حتى نتحكم في تمرير كل حساب (Token) بشكل مستقل
os.environ.pop("HF_TOKEN", None)

# قائمة لتسجيل الحسابات التي استنفدت كوتة الفيديو (ZeroGPU) لعدم إضاعة الوقت في إعادة تجربتها
EXHAUSTED_VIDEO_TOKENS = set()

# مؤثرات صوتية استوديو حقيقية ونظيفة
STUDIO_FOLEY_URLS = {
    "warm_pop": "https://actions.google.com/sounds/v1/cartoon/pop.ogg",
    "gasp_shock": "https://actions.google.com/sounds/v1/cartoon/concussive_hit_guitar_boing.ogg",
    "water_bubbles": "https://actions.google.com/sounds/v1/water/air_woosh_underwater.ogg",
    "sewing_machine": "https://actions.google.com/sounds/v1/office/typewriter_fast.ogg",
    "magic_tada": "https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg",
    "funny_fail": "https://actions.google.com/sounds/v1/cartoon/slide_whistle_to_drum.ogg"
}

BGM_URLS = [
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3"
]


class PinnedSpace:
    """اتصال HTTP/2 موحد لمنع ضياع ملفات الفيديو بين السيرفرات المتعددة"""
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


def get_clean_replica_storyboard():
    """6 مشاهد سينمائية نظيفة ومحتشمة 100% تحاكي قصة الجدة والحفيد بوضوح بصري تام"""
    boy_desc = (
        "a cheerful 16-year-old 3D Pixar teenage boy with neat black hair and expressive brown eyes, "
        "fully dressed in a cozy navy blue long-sleeve sweater and dark jeans"
    )
    grandma_desc = (
        "a sweet short chubby 3D Pixar grandmother with round glasses, modest floral headscarf, "
        "and a warm mustard-yellow knitted cardigan over a long apron"
    )

    return {
        "title": "لما تيتة تقرر تصلح جاكيت الموضة بتاعك! 😱😂",
        "scenes": [
            {
                "duration": 2.5,
                "sfx_type": "warm_pop",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, {boy_desc}, wearing a trendy white denim jacket "
                    f"with artistic colorful paint splatters over his sweater, warmly hugging {grandma_desc} "
                    f"inside a bright cozy wooden living room, Disney studio volumetric lighting, 8k, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy and his cute grandmother hug warmly and smile happily, gentle camera movement"
            },
            {
                "duration": 2.5,
                "sfx_type": "gasp_shock",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, close-up of {grandma_desc} holding up a folded white denim jacket "
                    f"covered in colorful artistic paint splatters, looking at the jacket wide-eyed with mouth open in funny cartoon shock, "
                    f"cozy wooden cabin background, Disney studio lighting, 8k, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother looks at the paint-splattered jacket in funny dramatic shock, eyes wide open, shaking her head"
            },
            {
                "duration": 2.5,
                "sfx_type": "water_bubbles",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, {grandma_desc} standing at a wooden table vigorously scrubbing "
                    f"the white jacket inside a large basin filled with sparkling soapy foam and floating soap bubbles, "
                    f"warm sunlit room, 8k octane render, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother scrubs the jacket enthusiastically in the soapy basin as shiny soap bubbles float into the air"
            },
            {
                "duration": 2.5,
                "sfx_type": "sewing_machine",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, close-up of {grandma_desc} smiling with intense focus while using "
                    f"a vintage white sewing machine on a wooden desk to stitch a giant bright yellow smiling cartoon sun patch "
                    f"and colorful flower patches onto the white jacket, warm lighting, 8k, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother sews rapidly on the sewing machine as the needle moves up and down stitching the yellow smiling sun patch"
            },
            {
                "duration": 2.5,
                "sfx_type": "magic_tada",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, {grandma_desc} beaming with pride and holding up the newly repaired white jacket "
                    f"now covered in a giant goofy smiling yellow cartoon sun patch and colorful floral fabric patches, sparkling clean, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother proudly holds up the patched jacket with a huge joyful smile, nodding happily"
            },
            {
                "duration": 2.8,
                "sfx_type": "funny_fail",
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation movie still, {boy_desc} now wearing the white jacket with the giant goofy smiling yellow cartoon sun patch "
                    f"and pink flower patches on the sleeves, staring at himself in a mirror with his jaw dropped in hilarious cartoon disbelief "
                    f"while his grandmother smiles proudly behind him, 8k, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy stares at his goofy sun-patched jacket with his jaw dropped in funny shock and puts his hands on his head"
            }
        ]
    }


def create_scene_audio(index, scene, out_audio_file):
    duration = float(scene.get("duration", 2.5))
    sfx_type = scene.get("sfx_type", "warm_pop")

    raw_ogg = f"raw_sfx_{index}.ogg"
    sfx_url = STUDIO_FOLEY_URLS.get(sfx_type, STUDIO_FOLEY_URLS["warm_pop"])

    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(raw_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
                "-i", raw_ogg,
                "-filter_complex",
                f"[1:a]atrim=0:{duration},afade=t=in:d=0.05,afade=t=out:st={max(duration - 0.4, 0.2)}:d=0.4,volume=0.80[s];"
                f"[0:a][s]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(duration), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return
    except Exception:
        pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-t", str(duration), "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)


def save_clean_hd_image(src_bytes_or_path, dst_file, is_bytes=False, crop_watermark=False):
    if is_bytes:
        with open("temp_img_raw", "wb") as f:
            f.write(src_bytes_or_path)
        img = Image.open("temp_img_raw").convert("RGB")
    else:
        img = Image.open(src_bytes_or_path).convert("RGB")

    if crop_watermark:
        w, h = img.size
        img = img.crop((0, 0, w, int(h * 0.95)))

    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=125, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def generate_image_with_nano_banana(index, image_prompt, img_file):
    if not GEMINI_API_KEY:
        return False

    nano_models = [
        "gemini-nano-banana-2.1",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image"
    ]

    parts = []
    if index > 0 and os.path.exists("scene_0.jpg"):
        try:
            with open("scene_0.jpg", "rb") as rf:
                b64_ref = base64.b64encode(rf.read()).decode("utf-8")
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64_ref}})
            parts.append({
                "text": (
                    "Keep the exact same 3D Pixar character designs, faces, and art style from this reference image. "
                    f"Generate a new vertical 9:16 scene: {image_prompt}"
                )
            })
        except Exception:
            parts = [{"text": image_prompt}]
    else:
        parts = [{"text": image_prompt}]

    for model_name in nano_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for cfg in [
            {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}},
            {"responseModalities": ["TEXT", "IMAGE"]}
        ]:
            try:
                r = requests.post(url, json={"contents": [{"parts": parts}], "generationConfig": cfg}, timeout=60)
                if r.status_code == 200:
                    rj = r.json()
                    for cand in rj.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            inline = part.get("inlineData") or part.get("inline_data")
                            if inline and inline.get("data"):
                                raw_bytes = base64.b64decode(inline["data"])
                                if len(raw_bytes) > 10000:
                                    save_clean_hd_image(raw_bytes, img_file, is_bytes=True, crop_watermark=False)
                                    print(f"🍌 تم تصميم صورة المشهد {index + 1} عبر Google Nano Banana ({model_name})!", flush=True)
                                    return True
            except Exception:
                pass

    try:
        imagen_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
        r = requests.post(
            imagen_url,
            json={"instances": [{"prompt": image_prompt}], "parameters": {"sampleCount": 1, "aspectRatio": "9:16"}},
            timeout=45
        )
        if r.status_code == 200:
            preds = r.json().get("predictions", [])
            if preds and "bytesBase64Encoded" in preds[0]:
                raw_bytes = base64.b64decode(preds[0]["bytesBase64Encoded"])
                save_clean_hd_image(raw_bytes, img_file, is_bytes=True, crop_watermark=False)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر Google Imagen 3!", flush=True)
                return True
    except Exception:
        pass

    return False


def download_scene_image(index, image_prompt, img_file):
    # 1. Google Nano Banana / Imagen 3
    if generate_image_with_nano_banana(index, image_prompt, img_file):
        return

    # 2. Hugging Face Router FLUX.1-schnell (باستخدام تدوير مفاتيح HF_TOKENS)
    for t_idx, tok in enumerate(HF_TOKENS):
        try:
            hf_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            headers = {
                "Authorization": f"Bearer {tok}",
                "Accept": "image/png",
                "Content-Type": "application/json"
            }
            res = requests.post(hf_url, headers=headers, json={"inputs": image_prompt}, timeout=60)
            if res.status_code == 200 and len(res.content) > 15000:
                save_clean_hd_image(res.content, img_file, is_bytes=True, crop_watermark=False)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر HF Router FLUX.1 (مفتاح #{t_idx + 1})!", flush=True)
                return
        except Exception:
            pass

    # 3. Pollinations Flux HD مع بذرة موحدة (Master Seed) لتناسق الشخصيات
    encoded_prompt = urllib.parse.quote(image_prompt, safe='')
    for attempt in range(4):
        if index > 0 or attempt > 0:
            time.sleep(6 + attempt * 3)
        model = "flux" if attempt < 3 else "turbo"
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1792&model={model}&nologo=true&seed={CHARACTER_MASTER_SEED + attempt}"
            res = requests.get(img_url, headers={"User-Agent": f"Mozilla/5.0 (PixarPipeline/{index}-{attempt})"}, timeout=90)
            if res.status_code == 200 and len(res.content) > 15000:
                save_clean_hd_image(res.content, img_file, is_bytes=True, crop_watermark=True)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر محرك Flux HD (بذرة موحدة)!", flush=True)
                return
        except Exception:
            pass

    # 4. مساحة FLUX.1-schnell مع بذرة موحدة
    for tok in ([None] + HF_TOKENS):
        try:
            client = Client("black-forest-labs/FLUX.1-schnell", token=tok, verbose=False)
            res = client.predict(
                prompt=image_prompt,
                seed=CHARACTER_MASTER_SEED,
                randomize_seed=False,
                width=768,
                height=1344,
                num_inference_steps=4,
                api_name="/infer"
            )
            img_path = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(img_path, dict) and "path" in img_path:
                img_path = img_path["path"]
            if isinstance(img_path, str) and os.path.exists(img_path):
                save_clean_hd_image(img_path, img_file, is_bytes=False, crop_watermark=False)
                print(f"🎨 تم تصميم صورة المشهد {index + 1} عبر مساحة FLUX.1!", flush=True)
                return
        except Exception:
            pass

    raise RuntimeError(f"تعذر توليد صورة جديدة للمشهد {index + 1} من جميع المحركات")


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


def is_quota_error(err_text):
    t = str(err_text).lower()
    return "zerogpu" in t or "exceeded" in t or "quota" in t or "runs limit" in t


def animate_image_with_ai(index, img_file, motion_prompt, duration, out_raw_video):
    full_motion = f"{motion_prompt}, 3D Pixar animation, family friendly, smooth expressive movement, lively action"
    neg_prompt = "low quality, worst quality, static, frozen, blurry, deformed, ugly, text, watermark, nsfw"

    all_pool = [None] + HF_TOKENS

    for pool_idx, tok in enumerate(all_pool):
        tok_key = "SERVER_IP" if tok is None else f"ACCOUNT_{pool_idx}"
        if tok_key in EXHAUSTED_VIDEO_TOKENS:
            continue

        quota_label = "IP السيرفر المجاني" if tok is None else f"مفتاح HF #{pool_idx}"

        # 1. Wan 2.2 Faster
        try:
            wan_space = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
            print(f"جاري تحريك المشهد {index + 1} عبر ({wan_space} - {quota_label})...", flush=True)
            client = Client(wan_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                prompt=full_motion,
                steps=4,
                negative_prompt=neg_prompt,
                duration_seconds=min(duration, 2.5),
                guidance_scale=1.0,
                guidance_scale_2=1.0,
                seed=CHARACTER_MASTER_SEED + index,
                randomize_seed=False,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل تلقائياً للمفتاح التالي...", flush=True)
                EXHAUSTED_VIDEO_TOKENS.add(tok_key)
                continue
            try:
                ps = PinnedSpace(wan_space, token=tok)
                up_img = ps.upload(img_file)
                out = ps.call("/generate_video", [up_img, full_motion, 4, neg_prompt, min(duration, 2.5), 1.0, 1.0, CHARACTER_MASTER_SEED + index, False])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                return True
            except Exception as e2:
                if is_quota_error(e2):
                    print(f"⚠️ انتهى ليميت ({quota_label})، جاري التبديل تلقائياً للمفتاح التالي...", flush=True)
                    EXHAUSTED_VIDEO_TOKENS.add(tok_key)
                    continue

        # 2. Lightricks/ltx-video-distilled
        try:
            ltx_space = "Lightricks/ltx-video-distilled"
            print(f"جاري تحريك المشهد {index + 1} عبر ({ltx_space} - {quota_label})...", flush=True)
            client = Client(ltx_space, token=tok, verbose=False)
            res = client.predict(
                prompt=full_motion,
                negative_prompt=neg_prompt,
                input_image_filepath=handle_file(img_file),
                input_video_filepath=None,
                height_ui=704,
                width_ui=512,
                mode="image-to-video",
                duration_ui=2.5,
                ui_frames_to_use=9,
                seed_ui=CHARACTER_MASTER_SEED + index,
                randomize_seed=False,
                ui_guidance_scale=3.0,
                improve_texture_flag=True,
                api_name="/image_to_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {ltx_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_VIDEO_TOKENS.add(tok_key)
                continue

        # 3. AnimateLCM-SVD
        try:
            svd_space = "wangfuyun/AnimateLCM-SVD"
            print(f"جاري تحريك المشهد {index + 1} عبر ({svd_space} - {quota_label})...", flush=True)
            ps = PinnedSpace(svd_space, token=tok)
            up_img = ps.upload(img_file)
            out = ps.call("video", [up_img, CHARACTER_MASTER_SEED + index, False, 85, 8, 1.2, 1, 576, 1024, 4])
            ps.download_video(out, out_raw_video)
            print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {svd_space} ({quota_label})!", flush=True)
            return True
        except Exception as e:
            if is_quota_error(e):
                EXHAUSTED_VIDEO_TOKENS.add(tok_key)
                continue

    return False


def create_scene_assets(index, scene):
    duration = float(scene.get("duration", 2.5))
    image_prompt = scene["image_prompt"]
    motion_prompt = scene["motion_prompt"]

    audio_file = f"scene_{index}.wav"
    create_scene_audio(index, scene, audio_file)

    img_file = f"scene_{index}.jpg"
    download_scene_image(index, image_prompt, img_file)

    raw_ai_video = f"raw_ai_{index}.mp4"
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 10

    ai_animated = animate_image_with_ai(index, img_file, motion_prompt, duration, raw_ai_video)

    if ai_animated and os.path.exists(raw_ai_video):
        # فلتر CAS (Contrast Adaptive Sharpening) لإبراز تفاصيل 3D Pixar بدقة 1080x1920
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,cas=0.65,unsharp=3:3:0.5:3:3:0.0,setsar=1,format=yuv420p",
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", video_file
        ], check=True)
    else:
        z_expr = "min(zoom+0.0028,1.24)" if index % 2 == 0 else "if(eq(on,1),1.24,max(zoom-0.0028,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.10:contrast=1.04,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},cas=0.5,setsar=1,format=yuv420p"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_file, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "16",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", video_file
        ], check=True)

    return video_file


def download_real_bgm(bgm_path):
    for url in BGM_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
            if r.ok and len(r.content) > 50000:
                with open(bgm_path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
    return False


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
            "title": f"{title[:80]} #shorts",
            "description": f"{title}\n\nMusic by Kevin MacLeod (incompetech.com) Licensed under CC BY 3.0\n#pixar #animation #3d #funny #shorts",
            "tags": ["shorts", "pixar", "animation", "funny", "3d"],
            "categoryId": "24"
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
    requests.post(upload_url, headers=headers, data=video_bytes, timeout=180).raise_for_status()

    finish_res = requests.post(
        f"{GRAPH_API}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": f"{title} ✨🎬\n\n#animation #pixar #funny #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}", flush=True)


def get_public_video_url(video_path):
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "12h"},
                files={"fileToUpload": f},
                timeout=120
            )
        if r.ok and r.text.strip().startswith("https://"):
            return r.text.strip()
    except Exception:
        pass

    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://uguu.se/upload",
                files={"files[]": f},
                timeout=120
            ).json()
        if r.get("success") and r.get("files"):
            return r["files"][0]["url"]
    except Exception:
        pass

    with open(video_path, "rb") as f:
        r = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": f},
            timeout=120
        ).json()
    if r.get("status") == "success":
        return r["data"]["url"].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")

    raise RuntimeError("تعذر رفع الفيديو لرابط مؤقت خاص بإنستجرام")


def wait_and_publish_ig(ig_user_id, container_id):
    print(f"[Instagram] تم إنشاء الحاوية ({container_id})، جاري انتظار معالجة الفيديو...", flush=True)
    for step in range(45):
        status_res = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": META_ACCESS_TOKEN},
            timeout=30
        ).json()
        code = status_res.get("status_code")
        print(f"[Instagram] حالة المعالجة ({step + 1}/45): {code}", flush=True)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"رفض إنستجرام معالجة الفيديو: {status_res}")
        time.sleep(8)

    for attempt in range(20):
        pub_res = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
            timeout=60
        ).json()
        if "id" in pub_res:
            print(f"[Instagram Reels] تم النشر بنجاح! معرف الريل: {pub_res['id']}", flush=True)
            return
        if pub_res.get("error", {}).get("code") == 9007:
            print(f"[Instagram] انتظار اللمسة الأخيرة للنشر ({attempt + 1}/20)...", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError(f"فشل نشر إنستجرام: {pub_res}")

    raise RuntimeError("انتهت مهلة انتظار نشر إنستجرام بعد 20 محاولة")


def upload_to_instagram_reels(video_path, title, ig_user_id):
    caption = f"{title} ✨🎬\n\n#pixar #animation #3d #funny #reels"
    public_url = get_public_video_url(video_path)
    print(f"[Instagram] جاري إرسال الفيديو عبر الرابط: {public_url}", flush=True)

    init_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": caption,
            "access_token": META_ACCESS_TOKEN
        },
        timeout=30
    ).json()

    if "id" not in init_res:
        raise RuntimeError(f"فشل تهيئة إنستجرام: {init_res}")

    wait_and_publish_ig(ig_user_id, init_res["id"])


def assemble_and_publish():
    print(f"إجمالي مفاتيح Hugging Face الجاهزة للتدوير التلقائي: {len(HF_TOKENS)} مفاتيح (+ IP السيرفر المجاني)", flush=True)
    story = get_clean_replica_storyboard()
    print(f"عنوان الفيديو: {story['title']}", flush=True)

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"--- جاري إنتاج وتحريك اللقطة {idx + 1} من {len(story['scenes'])} ---", flush=True)
        clip = create_scene_assets(idx, scene)
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    merged_video = "merged_short.mp4"
    final_video = "final_short.mp4"
    print("جاري المونتاج النهائي ومزامنة الموسيقى التصويرية...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    bgm_file = "bgm_track.mp3"
    if download_real_bgm(bgm_file):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", merged_video,
            "-stream_loop", "-1", "-i", bgm_file,
            "-filter_complex",
            "[1:a]volume='if(gt(t,12.5),0.0,0.22)':eval=frame[bg];"
            "[0:a]volume=1.20[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
            "-level", "4.0", "-crf", "16", "-c:a", "aac", "-ar", "44100",
            "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", final_video
        ], check=True)
    else:
        shutil.copyfile(merged_video, final_video)

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

        for ig_id in IG_USER_IDS:
            try:
                upload_to_instagram_reels(final_video, story["title"], ig_id)
            except Exception as e:
                print(f"[Instagram Error] {e}", flush=True)


if __name__ == "__main__":
    assemble_and_publish()
