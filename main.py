import os
import re
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
from PIL import Image, ImageFilter

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"

# ملاحظة هامة: لا نضع HF_TOKEN في os.environ العام حتى نستفيد من الكوتة المجانية للـ IP الخاص بـ GitHub Runner أولاً ثم كوتة الحساب!
os.environ.pop("HF_TOKEN", None)

# مؤثرات صوتية حقيقية (Foley & Human Reactions) مطابقة للفيديو المرجعي
STUDIO_FOLEY_URLS = {
    "cloth_hug": "https://actions.google.com/sounds/v1/foley/cloth_flapping.ogg",
    "put_down": "https://actions.google.com/sounds/v1/foley/footsteps_on_wood.ogg",
    "gasp_shock": "https://actions.google.com/sounds/v1/cartoon/concussive_hit_guitar_boing.ogg",
    "water_scrub": "https://actions.google.com/sounds/v1/water/waves_crashing_on_rock_beach.ogg",
    "sewing_machine": "https://actions.google.com/sounds/v1/office/typewriter_fast.ogg",
    "proud_tada": "https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg",
    "boy_groan": "https://actions.google.com/sounds/v1/cartoon/slide_whistle_to_drum.ogg",
    "faint_thud": "https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg"
}

BGM_URLS = [
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3",
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3"
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


def get_replica_storyboard():
    """
    النسخة المتطابقة لقطة بلقطة من فيديو الجدة والحفيد (@MAMA.CLUBNIKA):
    بدون حوار تقليدي، بدون ترجمة على الشاشة، مع تعبيرات صوتية ومؤثرات Foley حقيقية.
    """
    boy_desc = "a handsome 16-year-old 3D Pixar teenage boy with messy black hair and big expressive brown eyes"
    grandma_desc = "a sweet short chubby 3D Pixar grandmother with round glasses, floral headscarf, and mustard yellow knitted cardigan over an apron"

    return {
        "title": "لما تيتة تقرر تصلح لبسك الموضة! 😱😂",
        "scenes": [
            {
                "duration": 2.0,
                "sfx_type": "cloth_hug",
                "vocal_reaction": None,
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, {boy_desc} wearing black headphones around his neck, "
                    f"a white t-shirt with colorful paint splatters and a blue paint handprint, and ripped baggy blue jeans, "
                    f"warmly hugging {grandma_desc} inside a cozy sunlit wooden cabin, warm cinematic lighting, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy and his short chubby grandmother hug each other warmly and smile happily, smooth camera movement"
            },
            {
                "duration": 2.0,
                "sfx_type": "put_down",
                "vocal_reaction": None,
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, {boy_desc} wearing a white tank top and light blue shorts with yellow rubber duck pattern, "
                    f"placing his white t-shirt with blue handprint paint splatter and ripped blue jeans neatly onto a wooden chair in a wooden cabin, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy places his paint-splattered shirt and ripped jeans onto the wooden chair and turns around"
            },
            {
                "duration": 2.0,
                "sfx_type": "gasp_shock",
                "vocal_reaction": ("ar-EG-SalmaNeural", "+25%", "+18Hz", "هااا!"),
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, close-up of {grandma_desc} holding the white t-shirt with blue paint handprint, "
                    f"looking wide-eyed with mouth open in dramatic shock and horror, one hand on her chest, cozy wooden cabin background, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother gasps in dramatic shock, eyes wide open, putting her hand to her chest while looking at the shirt"
            },
            {
                "duration": 2.0,
                "sfx_type": "water_scrub",
                "vocal_reaction": None,
                "image_prompt": (
                    "Masterpiece 3D Pixar Disney animation, close-up high angle shot of grandmother's hands wearing mustard yellow knitted sleeves "
                    "vigorously scrubbing a white t-shirt inside a white enamel washbasin full of soapy water and fluffy white foam bubbles on a wooden table, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, hands vigorously scrubbing the white cloth in soapy water with bubbles splashing and moving rapidly"
            },
            {
                "duration": 2.2,
                "sfx_type": "sewing_machine",
                "vocal_reaction": None,
                "image_prompt": (
                    "Masterpiece 3D Pixar Disney animation, extreme close-up macro shot of a white sewing machine needle stitching a cute bright yellow smiling cartoon sun fabric patch "
                    "onto a white t-shirt, colorful threads, warm lighting, ultra detailed 3D textures, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the sewing machine needle moves up and down rapidly stitching the yellow sun patch as hands guide the fabric"
            },
            {
                "duration": 2.0,
                "sfx_type": "proud_tada",
                "vocal_reaction": ("ar-EG-SalmaNeural", "+15%", "+12Hz", "هممم!"),
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, {grandma_desc} beaming with pride and clapping her hands happily next to a wooden chair "
                    f"displaying blue jeans covered in colorful floral and red gingham checkered fabric patches, warm sunlit cabin, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the grandmother claps her hands joyfully and nods with a huge proud smile looking at the patched jeans"
            },
            {
                "duration": 2.4,
                "sfx_type": "boy_groan",
                "vocal_reaction": ("ar-EG-ShakirNeural", "-15%", "-10Hz", "آااااه!"),
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, medium close-up of {boy_desc} wearing a white t-shirt with a huge stitched smiling yellow cartoon sun patch on the chest "
                    f"and blue jeans with colorful floral and red checkered patches, staring down at his outfit with his jaw dropped in utter shock and disbelief, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy looks down at his giant smiling sun shirt in complete shock, his jaw drops open and he groans in disbelief"
            },
            {
                "duration": 2.2,
                "sfx_type": "faint_thud",
                "vocal_reaction": None,
                "image_prompt": (
                    f"Masterpiece 3D Pixar Disney animation, low angle shot of {boy_desc} wearing the white t-shirt with the big yellow smiling sun patch "
                    f"and colorful patched blue jeans, lying flat on his back passed out dramatically on the wooden cabin floor with arms spread out, vertical 9:16"
                ),
                "motion_prompt": "3D Pixar animation, the teenage boy collapses flat onto his back on the wooden floor in dramatic comedy faint, camera slight shake"
            }
        ]
    }


def create_scene_audio(index, scene, out_audio_file):
    """تصميم شريط صوتي سينمائي يدمج مؤثرات Foley الحقيقية مع الانفعالات الصوتية القصيرة بدون حوار آلي"""
    duration = scene.get("duration", 2.0)
    sfx_type = scene.get("sfx_type", "cloth_hug")
    vocal = scene.get("vocal_reaction")

    raw_ogg = f"raw_sfx_{index}.ogg"
    sfx_wav = f"sfx_{index}.wav"
    sfx_url = STUDIO_FOLEY_URLS.get(sfx_type, STUDIO_FOLEY_URLS["cloth_hug"])

    sfx_ok = False
    try:
        r = requests.get(sfx_url, timeout=20)
        if r.ok and len(r.content) > 1000:
            with open(raw_ogg, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-stream_loop", "2", "-i", raw_ogg,
                "-t", str(duration),
                "-af", f"afade=t=out:st={max(duration - 0.35, 0.2)}:d=0.35,volume=0.80",
                "-ar", "44100", "-ac", "2", sfx_wav
            ], check=True)
            sfx_ok = True
    except Exception:
        pass

    if not sfx_ok:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"anoisesrc=d={duration}:c=pink,lowpass=f=600,volume=0.3",
            "-ar", "44100", "-ac", "2", sfx_wav
        ], check=True)

    if vocal:
        voice_name, rate, pitch, exclaim = vocal
        vocal_mp3 = f"vocal_{index}.mp3"
        try:
            subprocess.run([
                "edge-tts", "--voice", voice_name,
                f"--rate={rate}", f"--pitch={pitch}",
                "--text", exclaim, "--write-media", vocal_mp3
            ], check=True, timeout=20, stderr=subprocess.DEVNULL)
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", sfx_wav, "-i", vocal_mp3,
                "-filter_complex",
                "[1:a]adelay=200|200,volume=1.3[v];[0:a][v]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "[a]", "-t", str(duration), "-ar", "44100", "-ac", "2", out_audio_file
            ], check=True)
            return
        except Exception:
            pass

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", sfx_wav, "-t", str(duration),
        "-ar", "44100", "-ac", "2", out_audio_file
    ], check=True)


def save_clean_hd_image(src_bytes_or_path, dst_file, is_bytes=False, crop_watermark=False):
    """حفظ الصورة بدقة 1080x1920 فائقة الحدة مع قص أي علامة مائية سفلية إن وجدت"""
    if is_bytes:
        with open("temp_img_raw", "wb") as f:
            f.write(src_bytes_or_path)
        img = Image.open("temp_img_raw").convert("RGB")
    else:
        img = Image.open(src_bytes_or_path).convert("RGB")

    if crop_watermark:
        w, h = img.size
        # قص 48 بكسل من الأسفل لإزالة شعار Pollinations تماماً قبل التكبير
        img = img.crop((0, 0, w, int(h * 0.96)))

    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=125, threshold=3))
    img.save(dst_file, "JPEG", quality=98)


def download_scene_image(index, image_prompt, img_file):
    """
    توليد صور 3D Pixar فائقة الجودة بدون استهلاك ثانية واحدة من رصيد ZeroGPU!
    (توفير 100% من رصيد ZeroGPU لتحريك الفيديو فقط)
    """
    # 1. المحرك الأول: Hugging Face Serverless Router (لا يستهلك ZeroGPU نهائياً)
    if HF_TOKEN:
        try:
            hf_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            headers = {"Authorization": f"Bearer {HF_TOKEN}"}
            payload = {
                "inputs": image_prompt,
                "parameters": {"width": 1024, "height": 1792, "num_inference_steps": 4}
            }
            res = requests.post(hf_url, headers=headers, json=payload, timeout=60)
            if res.status_code == 200 and len(res.content) > 15000:
                save_clean_hd_image(res.content, img_file, is_bytes=True, crop_watermark=False)
                print(f"تم تصميم صورة المشهد {index + 1} عبر HF Router FLUX.1 (بدون استهلاك ZeroGPU)!", flush=True)
                return
        except Exception:
            pass

    # 2. المحرك الثاني: Pollinations Flux HD مع قص نظيف 100% لأي علامة مائية
    encoded_prompt = urllib.parse.quote(image_prompt, safe='')
    base_seed = 202611 + (index * 101)
    for attempt, model in enumerate(["flux", "turbo"]):
        try:
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&model={model}&nologo=true&enhance=true&seed={base_seed + attempt}"
            res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=75)
            if res.status_code == 200 and len(res.content) > 15000:
                save_clean_hd_image(res.content, img_file, is_bytes=True, crop_watermark=True)
                print(f"تم تصميم صورة المشهد {index + 1} بجودة 3D Pixar HD نظيفة!", flush=True)
                return
        except Exception:
            pass
        time.sleep(3)

    if index > 0 and os.path.exists(f"scene_{index - 1}.jpg"):
        shutil.copyfile(f"scene_{index - 1}.jpg", img_file)
        return

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x1A1A2E:s=1080x1920:d=1",
        "-frames:v", "1", "-update", "1", img_file
    ], check=True)


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


def animate_image_with_ai(index, img_file, motion_prompt, duration, out_raw_video):
    """
    تحريك المشاهد بالذكاء الاصطناعي مع مضاعفة الرصيد المجاني:
    - يجرب أولاً بدون مفتاح (token=None) لاستغلال الـ IP الجديد المجاني لسيرفر GitHub Actions
    - ثم يجرب بمفتاح الحساب (token=HF_TOKEN)
    - يستخدم 4 خطوات سريعة ومدة قصيرة (2 ثانية) لتوفير الكوتة وتحريك أكبر عدد ممكن من المشاهد
    """
    full_motion = f"{motion_prompt}, 3D Pixar animation, smooth expressive movement, lively action"
    neg_prompt = "low quality, worst quality, static, frozen, blurry, deformed, ugly, text, watermark"

    tokens_to_try = [None]
    if HF_TOKEN:
        tokens_to_try.append(HF_TOKEN)

    for tok in tokens_to_try:
        quota_label = "IP السيرفر المجاني" if tok is None else "حساب HF"

        # 1. Wan 2.2 Faster (9 معاملات)
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
                seed=42 + index,
                randomize_seed=True,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} ({quota_label})!", flush=True)
                return True
        except Exception as e:
            if "not exist" in str(e).lower() or "404" in str(e).lower():
                try:
                    ps = PinnedSpace(wan_space, token=tok)
                    up_img = ps.upload(img_file)
                    out = ps.call("/generate_video", [up_img, full_motion, 4, neg_prompt, min(duration, 2.5), 1.0, 1.0, 42 + index, True])
                    ps.download_video(out, out_raw_video)
                    print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {wan_space} Pinned ({quota_label})!", flush=True)
                    return True
                except Exception:
                    pass

        # 2. Wan 2.2 Preview2 (10 معاملات شاملة last_image=None الذي ظهر في السجل)
        try:
            r3_space = "r3gm/wan2-2-fp8da-aoti-preview2"
            print(f"جاري تحريك المشهد {index + 1} عبر ({r3_space} - {quota_label})...", flush=True)
            client = Client(r3_space, token=tok, verbose=False)
            res = client.predict(
                input_image=handle_file(img_file),
                last_image=None,
                prompt=full_motion,
                steps=4,
                negative_prompt=neg_prompt,
                duration_seconds=min(duration, 2.5),
                guidance_scale=1.0,
                guidance_scale_2=1.0,
                seed=42 + index,
                randomize_seed=True,
                api_name="/generate_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {r3_space} ({quota_label})!", flush=True)
                return True
        except Exception:
            pass

        # 3. AnimateLCM-SVD (يستهلك 60 ثانية فقط من الكوتة)
        for svd_space in ["wangfuyun/AnimateLCM-SVD", "multimodalart/AnimateLCM-SVD-zerogpu"]:
            try:
                print(f"جاري تحريك المشهد {index + 1} عبر ({svd_space} - {quota_label})...", flush=True)
                ps = PinnedSpace(svd_space, token=tok)
                up_img = ps.upload(img_file)
                out = ps.call("video", [up_img, 42 + index, True, 85, 8, 1.2, 1, 576, 1024, 4])
                ps.download_video(out, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {svd_space} ({quota_label})!", flush=True)
                return True
            except Exception:
                pass

        # 4. LTX-Video Distilled
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
                duration_ui=2.0,
                ui_frames_to_use=9,
                seed_ui=42 + index,
                randomize_seed=True,
                ui_guidance_scale=3.0,
                improve_texture_flag=True,
                api_name="/image_to_video"
            )
            v_path = extract_video_path(res)
            if v_path:
                shutil.copyfile(v_path, out_raw_video)
                print(f"🎉 تم تحريك المشهد {index + 1} بنجاح عبر {ltx_space} ({quota_label})!", flush=True)
                return True
        except Exception:
            pass

    return False


def create_scene_assets(index, scene):
    duration = float(scene.get("duration", 2.0))
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
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", raw_ai_video, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,unsharp=3:3:0.6:3:3:0.0,setsar=1,format=yuv420p",
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "17",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", video_file
        ], check=True)
    else:
        # حركة كاميرا ديناميكية سريعة في حال امتلاء السيرفرات في مشهد معين
        z_expr = "min(zoom+0.0035,1.28)" if index % 2 == 0 else "if(eq(on,1),1.28,max(zoom-0.0035,1.0))"
        zoom_filter = (
            f"scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
            f"eq=saturation=1.12:contrast=1.04,"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps},setsar=1,format=yuv420p"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img_file, "-i", audio_file,
            "-map", "0:v", "-map", "1:a",
            "-vf", zoom_filter, "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "17",
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
    print("جاري تجهيز النسخة المتطابقة من فيديو الجدة والحفيد (@MAMA.CLUBNIKA)...", flush=True)
    story = get_replica_storyboard()
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
    print("جاري المونتاج النهائي ومزامنة الموسيقى التصويرية مع لحظة الصدمة...", flush=True)

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", merged_video
    ], check=True)

    bgm_file = "bgm_track.mp3"
    if download_real_bgm(bgm_file):
        # الموسيقى تعمل في المشاهد 1 إلى 6 (أول 12.2 ثانية) ثم تتوقف فجأة في لحظة صدمة الولد (تماماً مثل الفيديو الأصلي!)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", merged_video,
            "-stream_loop", "-1", "-i", bgm_file,
            "-filter_complex",
            "[1:a]volume='if(between(t,12.2,14.8),0.0,0.22)':eval=frame[bg];"
            "[0:a]volume=1.25[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-vf", "scale=1080:1920,setsar=1,format=yuv420p",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
            "-level", "4.0", "-crf", "17", "-c:a", "aac", "-ar", "44100",
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
