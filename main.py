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
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-AndrewMultilingualNeural").strip() or "en-US-AndrewMultilingualNeural"

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_BOLD_PATH = "Montserrat-ExtraBold.ttf"

SFX_LIBRARY = {
    "splash": ("https://actions.google.com/sounds/v1/water/water_splashing.ogg", 0.30),
    "turbine": ("https://actions.google.com/sounds/v1/science_fiction/sci_fi_osh.ogg", 0.25),
    "alarm": ("https://actions.google.com/sounds/v1/alarms/beep_short.ogg", 0.30),
    "clunk": ("https://actions.google.com/sounds/v1/impacts/heavy_thump.ogg", 0.35),
    "whoosh": ("https://actions.google.com/sounds/v1/foley/whoosh.ogg", 0.28),
    "bubbles": ("https://actions.google.com/sounds/v1/water/air_woosh_underwater.ogg", 0.28),
    "pop": ("https://actions.google.com/sounds/v1/cartoon/pop.ogg", 0.30),
    "cheer": ("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg", 0.30)
}


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


NUCLEAR_PLANT_SEGMENTS = [
    {
        "id": 0,
        "sfx": "splash",
        "cam_start": (500, 980, 1.35),
        "cam_end": (500, 1020, 1.65),
        "narration": "If you drop uranium into a tank of water, the uranium gets hot, and just like that, you have a nuclear reactor."
    },
    {
        "id": 1,
        "sfx": "turbine",
        "cam_start": (500, 1020, 1.65),
        "cam_end": (630, 1040, 1.25),
        "narration": "But hot water alone doesn't make electricity. So you seal the tank, let it boil, and use the steam to spin a turbine connected to a power generator."
    },
    {
        "id": 2,
        "sfx": "alarm",
        "cam_start": (630, 1040, 1.25),
        "cam_end": (480, 1030, 1.75),
        "narration": "The problem is, uranium keeps getting hotter and hotter. So you slide control rods between the fuel to absorb the reaction and cool it down."
    },
    {
        "id": 3,
        "sfx": "clunk",
        "cam_start": (480, 1030, 1.75),
        "cam_end": (480, 1000, 1.55),
        "narration": "In an emergency, you need to stop it instantly. So you hang the rods above the core on electromagnets. If the power cuts out, gravity drops them right in."
    },
    {
        "id": 4,
        "sfx": "bubbles",
        "cam_start": (480, 1000, 1.55),
        "cam_end": (580, 1020, 1.30),
        "narration": "However, the water touching the uranium becomes radioactive, and right now it's spinning your turbine. So you seal it inside its own closed loop, and use its heat to boil clean water in a second loop."
    },
    {
        "id": 5,
        "sfx": "splash",
        "cam_start": (580, 1020, 1.30),
        "cam_end": (780, 920, 1.40),
        "narration": "Next, you need to condense the steam back into water to reuse it. You can cool it with water from a river, but the river heats up so much it could literally cook the fish."
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "cam_start": (780, 920, 1.40),
        "cam_end": (980, 920, 1.35),
        "narration": "So instead, you build a giant cooling tower. Hot water rains down inside, rising air carries the heat away, and that white cloud on top is just pure water vapor."
    },
    {
        "id": 7,
        "sfx": "clunk",
        "cam_start": (980, 920, 1.35),
        "cam_end": (560, 1000, 1.25),
        "narration": "Still, if anything leaks, radiation could escape. So you surround the reactor with a massive steel and concrete containment dome over a meter thick."
    },
    {
        "id": 8,
        "sfx": "alarm",
        "cam_start": (560, 1000, 1.25),
        "cam_end": (420, 1020, 1.20),
        "narration": "But if the water pumps fail, the core will still overheat. So you add backup diesel generators, and an elevated water tank that floods the core using gravity alone."
    },
    {
        "id": 9,
        "sfx": "bubbles",
        "cam_start": (420, 1020, 1.20),
        "cam_end": (210, 1080, 1.65),
        "narration": "Even used nuclear fuel stays hot for years, so you submerge it in a deep water pool where it glows bright blue."
    },
    {
        "id": 10,
        "sfx": "pop",
        "cam_start": (210, 1080, 1.65),
        "cam_end": (210, 1120, 1.55),
        "narration": "Just one tiny uranium fuel pellet, the size of a gummy bear, produces as much electricity as an entire ton of coal."
    },
    {
        "id": 11,
        "sfx": "cheer",
        "cam_start": (210, 1120, 1.55),
        "cam_end": (600, 980, 0.92),
        "narration": "And congratulations! You just built a complete nuclear power plant."
    }
]


def generate_gemini_english_human_tts(narration_text, dst_wav):
    if not GEMINI_API_KEY:
        return False

    tts_models = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
    director_prompt = (
        "Speak as an engaging, clear, upbeat American science explainer YouTuber (like Zack D. Films or Kurzgesagt), "
        "with natural human rhythm and enthusiasm:\n"
        f"{narration_text}"
    )

    for model_name in tts_models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": director_prompt}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": "Puck"
                            }
                        }
                    }
                }
            }
            r = requests.post(url, json=payload, timeout=45)
            if r.status_code == 200:
                rj = r.json()
                for cand in rj.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        inline = part.get("inlineData") or part.get("inline_data")
                        if inline and inline.get("data"):
                            pcm_bytes = base64.b64decode(inline["data"])
                            if len(pcm_bytes) > 4000:
                                raw_pcm = "temp_gemini_voice.pcm"
                                with open(raw_pcm, "wb") as f:
                                    f.write(pcm_bytes)
                                subprocess.run([
                                    "ffmpeg", "-y", "-loglevel", "error",
                                    "-f", "s16le", "-ar", "24000", "-ac", "1",
                                    "-i", raw_pcm,
                                    "-ar", "44100", "-ac", "2", dst_wav
                                ], check=True)
                                return True
        except Exception:
            pass
    return False


def build_segment_audio(seg_idx, segment, out_wav):
    text = segment["narration"]
    sfx_key = segment["sfx"]

    raw_voice = f"seg_raw_{seg_idx}.wav"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = generate_gemini_english_human_tts(text, raw_voice)
    if not voice_ok:
        raw_mp3 = f"seg_raw_{seg_idx}.mp3"
        for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
            try:
                subprocess.run([
                    "edge-tts", "--voice", v_name, "--rate=+6%",
                    "--text", text, "--write-media", raw_mp3
                ], check=True, timeout=30, stderr=subprocess.DEVNULL)
                if os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 1000:
                    shutil.copyfile(raw_mp3, raw_voice)
                    voice_ok = True
                    break
            except Exception:
                time.sleep(1)

    if not voice_ok:
        encoded = urllib.parse.quote(text)
        r = requests.get(f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en&q={encoded}", timeout=30)
        with open(raw_voice, "wb") as f:
            f.write(r.content)

    warm_eq = "highpass=f=80,equalizer=f=190:width_type=o:width=1.5:g=2.5,equalizer=f=3800:width_type=o:width=2.0:g=2.0"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_voice,
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
    v_dur = float(probe.stdout.strip() or "5.0")
    final_dur = round(v_dur + 0.18, 2)

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


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def lerp(a, b, t):
    return a + (b - a) * t


class NuclearPlantRenderer:
    def __init__(self, font_path):
        self.font_word = ImageFont.truetype(font_path, 76)
        self.font_label = ImageFont.truetype(font_path, 30)
        self.font_gauge_num = ImageFont.truetype(font_path, 54)
        self.font_gauge_sub = ImageFont.truetype(font_path, 28)
        self.font_card = ImageFont.truetype(font_path, 34)

        random.seed(42)
        self.bubbles = [(random.uniform(0.15, 0.85), random.uniform(0.0, 1.0), random.uniform(6, 13)) for _ in range(28)]
        self.confetti = [
            (
                random.uniform(40, 1040),
                random.uniform(-600, 1200),
                random.uniform(4, 9),
                random.choice([(255, 80, 80), (60, 180, 255), (255, 215, 40), (80, 230, 120), (200, 100, 255)])
            )
            for _ in range(95)
        ]

    def world_to_screen(self, wx, wy, cam_x, cam_y, zoom):
        sx = (wx - cam_x) * zoom + 540.0
        sy = (wy - cam_y) * zoom + 960.0
        return sx, sy

    def draw_callout(self, draw, target_wx, target_wy, box_wx, box_wy, text, bg_color, cam_x, cam_y, zoom, alpha=1.0):
        if alpha <= 0.05:
            return
        tx, ty = self.world_to_screen(target_wx, target_wy, cam_x, cam_y, zoom)
        bx, by = self.world_to_screen(box_wx, box_wy, cam_x, cam_y, zoom)

        draw.line([(tx, ty), (bx, by)], fill=(35, 45, 55), width=max(int(3 * zoom), 2))
        r_dot = max(int(6 * zoom), 4)
        draw.ellipse([(tx - r_dot, ty - r_dot), (tx + r_dot, ty + r_dot)], fill=(255, 255, 255), outline=(35, 45, 55), width=2)

        bbox = draw.textbbox((0, 0), text, font=self.font_label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 22, 12
        rect = [bx - tw // 2 - pad_x, by - th // 2 - pad_y, bx + tw // 2 + pad_x, by + th // 2 + pad_y]
        draw.rounded_rectangle(rect, radius=22, fill=bg_color, outline=(255, 255, 255), width=3)
        draw.text((bx - tw // 2, by - th // 2 - 2), text, font=self.font_label, fill=(255, 255, 255))

    def draw_radiation_symbol(self, draw, sx, sy, radius):
        r = max(int(radius), 6)
        draw.ellipse([(sx - r, sy - r), (sx + r, sy + r)], fill=(250, 215, 40), outline=(30, 30, 30), width=2)
        for angle in (0, 120, 240):
            draw.pieslice([(sx - r + 2, sy - r + 2), (sx + r - 2, sy + r - 2)], start=angle, end=angle + 55, fill=(30, 30, 30))
        r_in = max(r // 4, 2)
        draw.ellipse([(sx - r_in, sy - r_in), (sx + r_in, sy + r_in)], fill=(250, 215, 40))

    def draw_temp_gauge(self, draw, temp_c, label="CORE TEMP"):
        card = [270, 1520, 810, 1710]
        draw.rounded_rectangle(card, radius=28, fill=(248, 246, 240), outline=(45, 55, 65), width=5)

        bar_bg = [310, 1555, 595, 1605]
        draw.rounded_rectangle(bar_bg, radius=22, fill=(230, 230, 230), outline=(55, 65, 75), width=3)

        ratio = max(0.08, min(1.0, (temp_c - 200.0) / 1000.0))
        fill_w = int((595 - 310 - 8) * ratio)
        bar_color = (230, 55, 45) if temp_c >= 700 else (45, 185, 85)
        draw.rounded_rectangle([314, 1559, 314 + fill_w, 1601], radius=18, fill=bar_color)

        t_str = f"{int(temp_c)}°C"
        draw.text((620, 1548), t_str, font=self.font_gauge_num, fill=bar_color)

        bbox = draw.textbbox((0, 0), label, font=self.font_gauge_sub)
        lw = bbox[2] - bbox[0]
        draw.text((540 - lw // 2, 1638), label, font=self.font_gauge_sub, fill=(45, 55, 65))

    def render_frame(self, seg_idx, seg_progress, global_time, current_word):
        img = Image.new("RGB", (1080, 1920), (115, 178, 235))
        draw = ImageDraw.Draw(img, "RGBA")

        seg = NUCLEAR_PLANT_SEGMENTS[seg_idx]
        ease_p = smoothstep(seg_progress)
        cam_x = lerp(seg["cam_start"][0], seg["cam_end"][0], ease_p)
        cam_y = lerp(seg["cam_start"][1], seg["cam_end"][1], ease_p)
        zoom = lerp(seg["cam_start"][2], seg["cam_end"][2], ease_p)

        def w2s(wx, wy):
            return self.world_to_screen(wx, wy, cam_x, cam_y, zoom)

        # 1. Sky, Sun & Clouds
        sun_x, sun_y = 870, 390
        for r_glow, a_glow in [(150, 35), (115, 65), (85, 110)]:
            draw.ellipse([(sun_x - r_glow, sun_y - r_glow), (sun_x + r_glow, sun_y + r_glow)], fill=(255, 235, 130, a_glow))
        draw.ellipse([(sun_x - 62, sun_y - 62), (sun_x + 62, sun_y + 62)], fill=(255, 248, 195))

        cloud_positions = [(180, 260, 1.0), (540, 330, 1.15), (820, 170, 0.9), (90, 480, 0.85)]
        for cx0, cy0, cscale in cloud_positions:
            cx = (cx0 + global_time * 8.0 * cscale) % 1280 - 100
            cy = cy0
            for dx, dy, rad in [(-55, 10, 48), (0, -12, 62), (55, 8, 50), (20, 18, 45)]:
                r_c = int(rad * cscale)
                draw.ellipse([(cx + dx * cscale - r_c, cy + dy * cscale - r_c), (cx + dx * cscale + r_c, cy + dy * cscale + r_c)], fill=(248, 250, 252))

        # 2. Ground, River, Fish & Road
        _, horizon_y = w2s(0, 680)
        _, river_top = w2s(0, 740)
        _, river_bot = w2s(0, 880)
        draw.rectangle([0, int(horizon_y), 1080, 1920], fill=(102, 182, 72))
        draw.rectangle([0, int(river_top), 1080, int(river_bot)], fill=(78, 165, 200))
        draw.line([(0, int(river_top)), (1080, int(river_top))], fill=(195, 175, 135), width=max(int(6 * zoom), 3))
        draw.line([(0, int(river_bot)), (1080, int(river_bot))], fill=(145, 115, 78), width=max(int(10 * zoom), 4))

        if seg_idx in (5, 6):
            rx1, ry1 = w2s(620, 775)
            rx2, ry2 = w2s(960, 865)
            plume_col = (225, 115, 75, 185) if seg_idx == 5 else (140, 175, 190, 110)
            draw.ellipse([rx1, ry1, rx2, ry2], fill=plume_col)
            if seg_idx == 5:
                for fx_off, fy_off in [(700, 805), (780, 825), (860, 810)]:
                    fx, fy = w2s(fx_off - seg_progress * 25, fy_off)
                    fish_c = (230, 155, 145) if seg_progress > 0.35 else (170, 185, 195)
                    fw, fh = int(34 * zoom), int(15 * zoom)
                    draw.ellipse([fx - fw, fy - fh, fx + fw, fy + fh], fill=fish_c, outline=(50, 60, 70), width=2)
                    draw.polygon([(fx + fw - 4, fy), (fx + fw + int(16 * zoom), fy - fh), (fx + fw + int(16 * zoom), fy + fh)], fill=fish_c, outline=(50, 60, 70))
                    draw.ellipse([fx - fw // 2 - 3, fy - 4, fx - fw // 2 + 3, fy + 2], fill=(20, 20, 20))

        boat_wx = 920 - (global_time * 12.0) % 700
        bx, by = w2s(boat_wx, 815)
        bw = int(28 * zoom)
        draw.polygon([(bx - bw, by), (bx + bw, by), (bx + int(bw * 0.7), by + int(12 * zoom)), (bx - int(bw * 0.7), by + int(12 * zoom))], fill=(140, 90, 50))
        draw.polygon([(bx, by - int(48 * zoom)), (bx, by - 2), (bx + int(24 * zoom), by - 2)], fill=(250, 250, 250), outline=(80, 80, 80))

        pad_pts = [w2s(100, 920), w2s(1120, 920), w2s(1180, 1270), w2s(40, 1270)]
        draw.polygon(pad_pts, fill=(216, 210, 197), outline=(165, 158, 145))

        road_pts = [w2s(-50, 1210), w2s(1200, 1310), w2s(1200, 1420), w2s(-50, 1310)]
        draw.polygon(road_pts, fill=(105, 110, 115), outline=(80, 85, 90))
        for r_i in range(8):
            lx1, ly1 = w2s(80 + r_i * 145, 1262 + r_i * 11)
            lx2, ly2 = w2s(135 + r_i * 145, 1266 + r_i * 11)
            draw.line([(lx1, ly1), (lx2, ly2)], fill=(245, 245, 245), width=max(int(5 * zoom), 3))

        b_tl = w2s(270, 835)
        b_br = w2s(450, 935)
        draw.rectangle([b_tl[0], b_tl[1], b_br[0], b_br[1]], fill=(228, 212, 182), outline=(120, 110, 95), width=2)
        sign_tl = w2s(295, 795)
        sign_br = w2s(425, 825)
        draw.rounded_rectangle([sign_tl[0], sign_tl[1], sign_br[0], sign_br[1]], radius=6, fill=(40, 45, 50), outline=(245, 205, 45), width=2)

        # 3. Containment Dome
        if seg_idx >= 7:
            dome_drop = smoothstep(seg_progress * 1.6) if seg_idx == 7 else 1.0
            dy_off = (1.0 - dome_drop) * -350
            d_tl = w2s(365, 740 + dy_off)
            d_br = w2s(695, 1155 + dy_off)
            draw.pieslice([d_tl[0], d_tl[1], d_br[0], d_br[1] + int(180 * zoom)], start=180, end=360, fill=(145, 150, 155), outline=(80, 85, 90), width=4)
            draw.rectangle([d_tl[0], (d_tl[1] + d_br[1]) // 2, d_br[0], d_br[1]], fill=(145, 150, 155), outline=(80, 85, 90), width=3)
            draw.arc([d_tl[0] - int(18 * zoom), d_tl[1] - int(18 * zoom), d_br[0] + int(18 * zoom), d_br[1] + int(180 * zoom)], start=180, end=360, fill=(210, 212, 215), width=max(int(22 * zoom), 8))
            draw.rectangle([d_tl[0] - int(20 * zoom), (d_tl[1] + d_br[1]) // 2, d_tl[0], d_br[1]], fill=(210, 212, 215), outline=(110, 115, 120), width=2)
            draw.rectangle([d_br[0], (d_tl[1] + d_br[1]) // 2, d_br[0] + int(20 * zoom), d_br[1]], fill=(210, 212, 215), outline=(110, 115, 120), width=2)

        # 4. Primary Reactor Tank + Uranium Rods + Control Rods
        t1_tl = w2s(415, 865)
        t1_br = w2s(535, 1140)
        base_tl = w2s(400, 1140)
        base_br = w2s(550, 1158)
        draw.rectangle([base_tl[0], base_tl[1], base_br[0], base_br[1]], fill=(200, 195, 185), outline=(235, 185, 35), width=3)
        draw.rectangle([t1_tl[0], t1_tl[1], t1_br[0], t1_br[1]], fill=(230, 238, 245), outline=(130, 145, 160), width=3)

        water_col = (125, 198, 190, 210) if seg_idx >= 4 else (115, 195, 235, 210)
        w1_tl = w2s(422, 910)
        w1_br = w2s(528, 1135)
        draw.rectangle([w1_tl[0], w1_tl[1], w1_br[0], w1_br[1]], fill=water_col)

        if seg_idx <= 1:
            c_tl = w2s(395, 780)
            c_br = w2s(555, 1150)
            draw.line([(c_tl[0], c_tl[1]), (c_tl[0], c_br[1])], fill=(235, 185, 40), width=max(int(10 * zoom), 4))
            draw.line([(c_br[0], c_tl[1]), (c_br[0], c_br[1])], fill=(235, 185, 40), width=max(int(10 * zoom), 4))
            draw.line([(c_tl[0], c_tl[1]), (c_br[0], c_tl[1])], fill=(235, 185, 40), width=max(int(12 * zoom), 5))

        rod_drop = smoothstep(seg_progress * 2.2) if seg_idx == 0 else 1.0
        rod_y_top = lerp(810, 995, rod_drop)
        rod_y_bot = rod_y_top + 125

        is_hot = (seg_idx == 0 and seg_progress > 0.45) or seg_idx in (1, 2, 3, 4, 5, 6, 7, 8)
        heat_intensity = 1.0 if seg_idx in (2, 8) else 0.65
        if is_hot:
            gx, gy = w2s(475, (rod_y_top + rod_y_bot) / 2)
            gr = int(75 * zoom * heat_intensity)
            draw.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=(255, 165, 50, int(95 * heat_intensity)))

        for r_i in range(5):
            rx1, ry1 = w2s(434 + r_i * 18, rod_y_top)
            rx2, ry2 = w2s(446 + r_i * 18, rod_y_bot)
            r_col = (245, 175, 65) if is_hot else (135, 95, 70)
            draw.rectangle([rx1, ry1, rx2, ry2], fill=r_col, outline=(90, 65, 45), width=1)

        cap1_tl, cap1_br = w2s(430, rod_y_top - 8), w2s(520, rod_y_top)
        cap2_tl, cap2_br = w2s(430, rod_y_bot), w2s(520, rod_y_bot + 8)
        draw.rectangle([cap1_tl[0], cap1_tl[1], cap1_br[0], cap1_br[1]], fill=(120, 130, 140))
        draw.rectangle([cap2_tl[0], cap2_tl[1], cap2_br[0], cap2_br[1]], fill=(120, 130, 140))

        if seg_idx >= 2:
            if seg_idx == 2:
                ctrl_depth = smoothstep((seg_progress - 0.35) * 1.8)
            elif seg_idx == 3:
                ctrl_depth = 1.0 if seg_progress > 0.58 else 0.25
            else:
                ctrl_depth = 0.55

            c_top = lerp(845, 935, ctrl_depth)
            c_bot = c_top + 95
            for c_i in range(3):
                cx1, cy1 = w2s(444 + c_i * 26, c_top)
                cx2, cy2 = w2s(454 + c_i * 26, c_bot)
                draw.rectangle([cx1, cy1, cx2, cy2], fill=(70, 78, 85), outline=(40, 45, 50), width=1)

                if seg_idx >= 3:
                    mx1, my1 = w2s(440 + c_i * 26, 875)
                    mx2, my2 = w2s(458 + c_i * 26, 898)
                    draw.rectangle([mx1, my1, mx2, my2], fill=(215, 55, 45), outline=(250, 205, 50), width=2)

        if (seg_idx == 0 and seg_progress > 0.5) or seg_idx >= 1:
            for bx_norm, by_seed, b_rad in self.bubbles[:16]:
                by_prog = (by_seed + global_time * 0.55) % 1.0
                b_wx = lerp(432, 518, bx_norm)
                b_wy = lerp(1020, 912, by_prog)
                bsx, bsy = w2s(b_wx, b_wy)
                br = max(int(b_rad * 0.45 * zoom), 3)
                draw.ellipse([bsx - br, bsy - br, bsx + br, bsy + br], fill=(255, 255, 255, 195))

        if seg_idx >= 4:
            for rad_wx, rad_wy in [(445, 960), (485, 945), (505, 980), (460, 995)]:
                rsx, rsy = w2s(rad_wx, rad_wy + math.sin(global_time * 3 + rad_wx) * 6)
                self.draw_radiation_symbol(draw, rsx, rsy, 7 * zoom)

        # 5. Secondary Clean Water Loop
        if seg_idx >= 4:
            t2_tl = w2s(575, 865)
            t2_br = w2s(665, 1140)
            draw.rectangle([t2_tl[0], t2_tl[1], t2_br[0], t2_br[1]], fill=(225, 235, 245), outline=(130, 145, 160), width=3)
            w2_tl = w2s(582, 935)
            w2_br = w2s(658, 1135)
            draw.rectangle([w2_tl[0], w2_tl[1], w2_br[0], w2_br[1]], fill=(120, 198, 240, 210))

            p_hot1, p_hot2 = w2s(528, 995), w2s(585, 1012)
            p_cold1, p_cold2 = w2s(528, 1085), w2s(585, 1102)
            draw.rounded_rectangle([p_hot1[0], p_hot1[1], p_hot2[0], p_hot2[1]], radius=8, fill=(240, 105, 55))
            draw.rounded_rectangle([p_cold1[0], p_cold1[1], p_cold2[0], p_cold2[1]], radius=8, fill=(75, 165, 235))

            coil_tl, coil_br = w2s(596, 975), w2s(644, 1120)
            draw.arc([coil_tl[0], coil_tl[1], coil_br[0], coil_br[1]], start=180, end=360, fill=(235, 125, 65), width=max(int(5 * zoom), 3))
            draw.line([(coil_tl[0], (coil_tl[1] + coil_br[1]) // 2), (coil_tl[0], coil_br[1])], fill=(235, 125, 65), width=max(int(5 * zoom), 3))
            draw.line([(coil_br[0], (coil_tl[1] + coil_br[1]) // 2), (coil_br[0], coil_br[1])], fill=(235, 125, 65), width=max(int(5 * zoom), 3))

            pmp_x, pmp_y = w2s(556, 1093)
            pmp_r = int(14 * zoom)
            draw.ellipse([pmp_x - pmp_r, pmp_y - pmp_r, pmp_x + pmp_r, pmp_y + pmp_r], fill=(55, 65, 75), outline=(255, 255, 255), width=2)
            if seg_idx == 8:
                draw.line([(pmp_x - pmp_r, pmp_y - pmp_r), (pmp_x + pmp_r, pmp_y + pmp_r)], fill=(235, 45, 45), width=4)
                draw.line([(pmp_x + pmp_r, pmp_y - pmp_r), (pmp_x - pmp_r, pmp_y + pmp_r)], fill=(235, 45, 45), width=4)

        # 6. Steam Pipe + Spinning Turbine + Generator + Lamp
        if seg_idx >= 1:
            pipe_src_x = 620 if seg_idx >= 4 else 475
            ps1 = w2s(pipe_src_x, 865)
            ps2 = w2s(pipe_src_x, 815)
            ps3 = w2s(760, 815)
            ps4 = w2s(760, 1040)
            pw = max(int(16 * zoom), 6)
            draw.line([ps1, ps2, ps3, ps4], fill=(210, 218, 225), width=pw, joint="curve")

            tb_x, tb_y = w2s(765, 1065)
            tb_w, tb_h = int(52 * zoom), int(28 * zoom)
            draw.rectangle([tb_x - tb_w, tb_y - tb_h, tb_x + tb_w, tb_y + tb_h], fill=(165, 175, 185), outline=(90, 100, 110), width=2)
            spin_phase = global_time * 12.0
            for b_i in range(6):
                bx_blade = tb_x - tb_w + int((b_i + 0.5) * (2 * tb_w / 6))
                bh_blade = int(tb_h * (0.4 + 0.6 * abs(math.sin(spin_phase + b_i * 0.9))))
                draw.polygon([
                    (bx_blade - int(7 * zoom), tb_y - bh_blade),
                    (bx_blade + int(7 * zoom), tb_y),
                    (bx_blade - int(7 * zoom), tb_y + bh_blade)
                ], fill=(245, 248, 252), outline=(120, 130, 140))

            gen_tl = w2s(830, 1015)
            gen_br = w2s(920, 1125)
            draw.rectangle([gen_tl[0], gen_tl[1], gen_br[0], gen_br[1]], fill=(68, 178, 142), outline=(45, 125, 98), width=3)

            lamp_base = w2s(965, 1140)
            lamp_top = w2s(965, 1020)
            draw.line([lamp_base, lamp_top], fill=(70, 75, 80), width=max(int(5 * zoom), 3))
            lr = int(18 * zoom)
            draw.ellipse([lamp_top[0] - lr * 2, lamp_top[1] - lr * 2, lamp_top[0] + lr * 2, lamp_top[1] + lr * 2], fill=(255, 240, 120, 95))
            draw.ellipse([lamp_top[0] - lr, lamp_top[1] - lr, lamp_top[0] + lr, lamp_top[1] + lr], fill=(255, 245, 150), outline=(120, 110, 60), width=2)

        # 7. Condenser & Cooling Tower
        if seg_idx >= 5:
            cond_tl = w2s(760, 945)
            cond_br = w2s(835, 1005)
            draw.rectangle([cond_tl[0], cond_tl[1], cond_br[0], cond_br[1]], fill=(145, 190, 220), outline=(95, 135, 165), width=2)

        if seg_idx >= 6:
            ct_top_l, ct_top_r = w2s(955, 730), w2s(1065, 730)
            ct_mid_l, ct_mid_r = w2s(968, 845), w2s(1052, 845)
            ct_bot_l, ct_bot_r = w2s(930, 1025), w2s(1090, 1025)

            tower_alpha = 155 if seg_idx == 6 else 255
            tower_col = (218, 212, 198, tower_alpha)
            draw.polygon([ct_top_l, ct_top_r, ct_mid_r, ct_bot_r, ct_bot_l, ct_mid_l], fill=tower_col, outline=(140, 135, 125))

            for s_i in range(5):
                s_prog = (s_i * 0.2 + global_time * 0.35) % 1.0
                sx_c, sy_c = w2s(1010 + math.sin(s_prog * 5) * 18, 720 - s_prog * 140)
                sr = int((28 + s_prog * 38) * zoom)
                draw.ellipse([sx_c - sr, sy_c - sr, sx_c + sr, sy_c + sr], fill=(255, 255, 255, int(210 * (1.0 - s_prog * 0.65))))

        # 8. Backup Generators & Gravity Water Tank
        if seg_idx >= 8:
            gen2_tl, gen2_br = w2s(245, 1045), w2s(325, 1135)
            draw.rectangle([gen2_tl[0], gen2_tl[1], gen2_br[0], gen2_br[1]], fill=(242, 198, 52), outline=(165, 130, 30), width=2)
            wt_tl, wt_br = w2s(255, 815), w2s(345, 895)
            leg1, leg2 = w2s(270, 1135), w2s(330, 1135)
            draw.line([(wt_tl[0] + 10, wt_br[1]), leg1], fill=(95, 105, 115), width=max(int(5 * zoom), 3))
            draw.line([(wt_br[0] - 10, wt_br[1]), leg2], fill=(95, 105, 115), width=max(int(5 * zoom), 3))
            draw.rectangle([wt_tl[0], wt_tl[1], wt_br[0], wt_br[1]], fill=(135, 195, 230), outline=(85, 135, 165), width=3)

        # 9. Spent Fuel Pool & Blue Cherenkov Glow
        if seg_idx >= 9:
            pool_tl, pool_br = w2s(125, 1045), w2s(235, 1155)
            draw.rectangle([pool_tl[0], pool_tl[1], pool_br[0], pool_br[1]], fill=(225, 232, 238), outline=(130, 140, 150), width=3)
            pw_tl, pw_br = w2s(133, 1060), w2s(227, 1145)
            draw.rectangle([pw_tl[0], pw_tl[1], pw_br[0], pw_br[1]], fill=(85, 185, 245, 225))
            cg_x, cg_y = w2s(180, 1105)
            c_rad = int(42 * zoom)
            draw.ellipse([cg_x - c_rad, cg_y - c_rad, cg_x + c_rad, cg_y + c_rad], fill=(120, 225, 255, 140))

        # 10. Callout Labels & Gauges
        if seg_idx == 0:
            self.draw_callout(draw, 475, 1045, 675, 965, "URANIUM FUEL", (215, 135, 45), cam_x, cam_y, zoom)
            self.draw_callout(draw, 425, 1090, 260, 1140, "WATER TANK", (105, 165, 205), cam_x, cam_y, zoom)
        elif seg_idx == 1:
            self.draw_callout(draw, 475, 835, 310, 825, "STEAM", (135, 155, 170), cam_x, cam_y, zoom)
            self.draw_callout(draw, 765, 1055, 680, 945, "TURBINE", (120, 140, 155), cam_x, cam_y, zoom)
            self.draw_callout(draw, 875, 1040, 875, 920, "GENERATOR", (68, 178, 142), cam_x, cam_y, zoom)
        elif seg_idx == 2:
            if seg_progress < 0.48:
                temp_val = lerp(468, 1200, seg_progress / 0.48)
            else:
                temp_val = lerp(1200, 300, (seg_progress - 0.48) / 0.52)
            self.draw_temp_gauge(draw, temp_val, "CORE TEMPERATURE")
            if seg_progress > 0.45:
                self.draw_callout(draw, 495, 965, 685, 945, "CONTROL RODS", (65, 75, 85), cam_x, cam_y, zoom)
        elif seg_idx == 3:
            self.draw_callout(draw, 475, 885, 680, 880, "ELECTROMAGNETS", (215, 55, 45), cam_x, cam_y, zoom)
        elif seg_idx == 4:
            self.draw_callout(draw, 555, 1045, 555, 1190, "CLOSED LOOP", (215, 135, 45), cam_x, cam_y, zoom)
            self.draw_callout(draw, 620, 995, 780, 940, "SECONDARY LOOP", (85, 165, 220), cam_x, cam_y, zoom)
        elif seg_idx == 5:
            self.draw_callout(draw, 795, 965, 650, 895, "STEAM -> WATER", (85, 165, 220), cam_x, cam_y, zoom)
            if seg_progress > 0.45:
                self.draw_temp_gauge(draw, 70, "RIVER WATER TEMP")
        elif seg_idx == 6:
            self.draw_callout(draw, 1010, 865, 790, 835, "COOLING TOWER", (145, 140, 130), cam_x, cam_y, zoom)
            self.draw_callout(draw, 1010, 665, 1010, 560, "PURE H2O VAPOR", (75, 155, 215), cam_x, cam_y, zoom)
        elif seg_idx == 7:
            self.draw_callout(draw, 530, 755, 530, 660, "CONTAINMENT DOME (+1m)", (115, 120, 125), cam_x, cam_y, zoom)
        elif seg_idx == 8:
            self.draw_temp_gauge(draw, lerp(745, 1064, min(seg_progress * 1.5, 1.0)), "CORE TEMPERATURE")
            self.draw_callout(draw, 285, 1070, 210, 960, "BACKUP GENERATORS", (215, 165, 35), cam_x, cam_y, zoom)
            self.draw_callout(draw, 300, 845, 300, 735, "GRAVITY WATER TANK", (85, 165, 220), cam_x, cam_y, zoom)
        elif seg_idx == 9:
            self.draw_callout(draw, 180, 1100, 340, 990, "SPENT FUEL POOL", (65, 155, 225), cam_x, cam_y, zoom)
        elif seg_idx == 10:
            c_box = [130, 1150, 950, 1640]
            draw.rounded_rectangle(c_box, radius=32, fill=(250, 246, 235), outline=(45, 55, 65), width=5)
            draw.rounded_rectangle([240, 1330, 305, 1415], radius=12, fill=(125, 135, 145), outline=(40, 45, 50), width=4)
            draw.ellipse([345, 1320, 405, 1375], fill=(235, 65, 55), outline=(140, 30, 25), width=3)
            draw.rounded_rectangle([340, 1355, 410, 1415], radius=18, fill=(235, 65, 55), outline=(140, 30, 25), width=3)
            draw.text((205, 1465), "1 FUEL PELLET", font=self.font_card, fill=(40, 45, 50))
            draw.text((515, 1340), "=", font=self.font_word, fill=(235, 165, 40))
            for cx_c, cy_c in [(690, 1395), (745, 1395), (800, 1395), (715, 1350), (770, 1350), (742, 1305)]:
                draw.regular_polygon((cx_c, cy_c, 34), n_sides=6, fill=(55, 60, 65), outline=(25, 30, 35))
            draw.text((645, 1465), "1 TON OF COAL", font=self.font_card, fill=(40, 45, 50))
        elif seg_idx == 11:
            for c_x, c_y0, c_s, c_col in self.confetti:
                cy_now = (c_y0 + seg_progress * 950) % 1920
                cx_now = c_x + math.sin(global_time * 5 + c_x) * 18
                draw.rectangle([cx_now - c_s, cy_now - c_s * 1.6, cx_now + c_s, cy_now + c_s * 1.6], fill=c_col)

        # 11. Top Center Word-by-Word Pop Caption
        if current_word:
            w_text = current_word.upper()
            bbox = draw.textbbox((0, 0), w_text, font=self.font_word)
            tw = bbox[2] - bbox[0]
            wx_pos = (1080 - tw) // 2
            wy_pos = 360

            for dx in (-5, -3, 0, 3, 5):
                for dy in (-5, -3, 0, 3, 5):
                    if dx != 0 or dy != 0:
                        draw.text((wx_pos + dx, wy_pos + dy), w_text, font=self.font_word, fill=(35, 45, 55))
            draw.text((wx_pos, wy_pos), w_text, font=self.font_word, fill=(255, 255, 255))

        return img


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
            "title": f"{title[:80]} #engineering #science #nuclear #howitworks #shorts",
            "description": f"{title}\n\nStep-by-step animated explainer on how a nuclear power plant works.\n#engineering #science #howitworks #nuclearpower #technology #shorts",
            "tags": ["nuclear power plant", "how it works", "engineering", "science", "animation", "shorts"],
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
    title = "How to Build a Nuclear Power Plant Step-by-Step! ⚛️⚡"
    font_path = ensure_english_font()
    renderer = NuclearPlantRenderer(font_path)

    print("🎙️ Step 1: Generating Natural English Voiceover & SFX for all 12 stages...", flush=True)
    seg_audios = []
    seg_durations = []
    for idx, seg in enumerate(NUCLEAR_PLANT_SEGMENTS):
        wav_file = f"seg_{idx}.wav"
        dur = build_segment_audio(idx, seg, wav_file)
        seg_audios.append(wav_file)
        seg_durations.append(dur)
        print(f"  ✓ Stage {idx + 1}/12 audio ready ({dur}s)", flush=True)

    total_duration = round(sum(seg_durations), 2)
    print(f"⏱️ Total Explainer Duration: {total_duration}s ({round(total_duration / 60, 2)} minutes)!", flush=True)

    with open("audio_list.txt", "w") as f:
        for w in seg_audios:
            f.write(f"file '{w}'\n")

    master_audio = "master_audio.wav"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", "audio_list.txt", "-c", "copy", master_audio
    ], check=True)

    print("🎬 Step 2: Rendering Continuous 30-FPS Programmatic Animation Stream...", flush=True)
    fps = 30
    raw_video = "raw_programmatic.mp4"
    ffmpeg_proc = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1080x1920", "-pix_fmt", "rgb24", "-r", str(fps),
        "-i", "-",
        "-i", master_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "16",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-shortest", raw_video
    ], stdin=subprocess.PIPE)

    global_t = 0.0
    dt = 1.0 / fps
    for seg_idx, seg in enumerate(NUCLEAR_PLANT_SEGMENTS):
        seg_dur = seg_durations[seg_idx]
        seg_frames = max(int(round(seg_dur * fps)), 1)
        words = re.sub(r'[,.?!—-]', '', seg["narration"]).split() or [""]

        for f_i in range(seg_frames):
            prog = f_i / max(seg_frames - 1, 1)
            w_idx = min(int(prog * len(words)), len(words) - 1)
            curr_word = words[w_idx]

            frame_img = renderer.render_frame(seg_idx, prog, global_t, curr_word)
            ffmpeg_proc.stdin.write(frame_img.tobytes())
            global_t += dt

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()

    final_video = "final_short.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.006",
        "-filter_complex",
        "[1:a]lowpass=f=260[bg];[0:a]volume=1.15[fg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-movflags", "+faststart", final_video
    ], check=True)

    print("🚀 Step 3: Publishing to YouTube & Facebook Reels...", flush=True)
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


if __name__ == "__main__":
    assemble_and_publish()
