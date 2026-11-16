import os
import re
import math
import time
import random
import shutil
import urllib.parse
import subprocess
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-AndrewMultilingualNeural").strip() or "en-US-AndrewMultilingualNeural"

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"
FONT_BOLD_PATH = "Montserrat-ExtraBold.ttf"

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

# الـ 12 مرحلة الكاملة لبناء المحطة النووية ثلاثية الأبعاد (3D Isometric Camera Coordinates)
NUCLEAR_PLANT_SEGMENTS = [
    {
        "id": 0,
        "sfx": "splash",
        "cam_start": (-2.0, 3.2, 0.0, 1.35),
        "cam_end": (-2.2, 3.0, 0.0, 1.62),
        "narration": "If you drop uranium into a tank of water, the uranium gets hot, and you have a nuclear reactor."
    },
    {
        "id": 1,
        "sfx": "turbine",
        "cam_start": (-2.2, 3.0, 0.0, 1.62),
        "cam_end": (2.2, 2.8, 0.0, 1.18),
        "narration": "But hot water doesn't make electricity. So you let it boil, and use steam to spin a turbine connected to a generator."
    },
    {
        "id": 2,
        "sfx": "alarm",
        "cam_start": (2.2, 2.8, 0.0, 1.18),
        "cam_end": (-2.2, 3.0, 0.0, 1.68),
        "narration": "However, uranium keeps getting hotter and hotter. So you slide control rods between the fuel to absorb the reaction and cool it down."
    },
    {
        "id": 3,
        "sfx": "clunk",
        "cam_start": (-2.2, 3.0, 0.0, 1.68),
        "cam_end": (-2.2, 3.3, 0.0, 1.52),
        "narration": "In an emergency, you need to stop it fast. So you hang the rods above the core on electromagnets. If power cuts out, they drop right in."
    },
    {
        "id": 4,
        "sfx": "bubbles",
        "cam_start": (-2.2, 3.3, 0.0, 1.52),
        "cam_end": (0.2, 3.0, 0.0, 1.32),
        "narration": "But water touching uranium gets radioactive, and right now it spins your turbine. So you seal it in a closed loop to boil clean water in a second loop."
    },
    {
        "id": 5,
        "sfx": "splash",
        "cam_start": (0.2, 3.0, 0.0, 1.32),
        "cam_end": (5.0, 3.8, -3.0, 1.28),
        "narration": "Next, you condense the steam back into water to reuse it. You can cool it with river water, but the river heats up enough to cook the fish."
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "cam_start": (5.0, 3.8, -3.0, 1.28),
        "cam_end": (8.8, 4.2, -1.0, 1.22),
        "narration": "So you build a giant cooling tower. Hot water rains down inside, air carries heat up, and that cloud on top is just pure water vapor."
    },
    {
        "id": 7,
        "sfx": "clunk",
        "cam_start": (8.8, 4.2, -1.0, 1.22),
        "cam_end": (0.5, 3.5, 0.0, 1.15),
        "narration": "If anything leaks, radiation could escape. So you build a steel and concrete containment dome over a meter thick around the reactor."
    },
    {
        "id": 8,
        "sfx": "alarm",
        "cam_start": (0.5, 3.5, 0.0, 1.15),
        "cam_end": (-3.2, 3.2, 0.0, 1.18),
        "narration": "If the pumps fail, the core will overheat. So you add backup generators, and a high water tank that floods the core by gravity alone."
    },
    {
        "id": 9,
        "sfx": "bubbles",
        "cam_start": (-3.2, 3.2, 0.0, 1.18),
        "cam_end": (-8.5, 2.0, 1.5, 1.55),
        "narration": "Used nuclear fuel stays hot for years, so you submerge it in a deep water pool where it glows bright blue."
    },
    {
        "id": 10,
        "sfx": "pop",
        "cam_start": (-8.5, 2.0, 1.5, 1.55),
        "cam_end": (-8.5, 1.5, 1.5, 1.45),
        "narration": "One tiny uranium fuel pellet, the size of a gummy bear, produces as much electricity as an entire ton of coal."
    },
    {
        "id": 11,
        "sfx": "cheer",
        "cam_start": (-8.5, 1.5, 1.5, 1.45),
        "cam_end": (1.0, 3.2, 0.0, 0.86),
        "narration": "And congratulations! You just built a nuclear power plant."
    }
]


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


def build_segment_audio(seg_idx, segment, out_wav):
    """
    توليد الصوت الأمريكي الموحد في أقل من ثانية لكل مرحلة بدون أي انتظار (Zero Waiting)
    وبنفس صوت المتحدث من أول ثانية لآخر ثانية!
    """
    text = segment["narration"]
    sfx_key = segment["sfx"]

    raw_mp3 = f"seg_raw_{seg_idx}.mp3"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural"]:
        try:
            subprocess.run([
                "edge-tts", "--voice", v_name, "--rate=+10%",
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
    final_dur = round(v_dur + 0.14, 2)

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
                f"[1:a]atrim=0:{min(final_dur, 1.8)},afade=t=in:d=0.04,afade=t=out:st={max(min(final_dur, 1.8) - 0.3, 0.1)}:d=0.3,volume={sfx_vol}[s];"
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


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def shade_rgb(rgb, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


class True3DIsometricRenderer:
    """
    محرك إسقاط ثلاثي الأبعاد حقيقي ومباشر (True 3D Isometric/Perspective Projection Engine):
    يحول الإحداثيات الثلاثية (X, Y, Z) إلى مجسمات ثلاثية الأبعاد بـ 3 أوجه مظللة وأسطوانات مقطوعة 3D
    بسرعة فائقة بدون الحاجة لتحميل أي متصفح خارجي!
    """
    def __init__(self, font_path):
        self.font_word = ImageFont.truetype(font_path, 76)
        self.font_label = ImageFont.truetype(font_path, 28)
        self.font_gauge_num = ImageFont.truetype(font_path, 52)
        self.font_gauge_sub = ImageFont.truetype(font_path, 26)
        self.font_card = ImageFont.truetype(font_path, 32)

        # زاوية الكاميرا الثلاثية الأبعاد (مطابقة لزاوية الفيديو المرجعي بالضبط)
        self.yaw = math.radians(-22.0)
        self.pitch = math.radians(19.0)
        self.base_scale = 52.0

        random.seed(42)
        self.bubbles = [(random.uniform(-0.9, 0.9), random.uniform(0.0, 1.0), random.uniform(-0.4, 0.4), random.uniform(5, 11)) for _ in range(26)]
        self.confetti = [
            (
                random.uniform(40, 1040),
                random.uniform(-600, 1200),
                random.uniform(5, 10),
                random.choice([(255, 80, 80), (60, 180, 255), (255, 215, 40), (80, 230, 120), (200, 100, 255)])
            )
            for _ in range(90)
        ]

    def project(self, x, y, z, cam_target, zoom):
        dx = x - cam_target[0]
        dy = y - cam_target[1]
        dz = z - cam_target[2]

        rx = dx * math.cos(self.yaw) + dz * math.sin(self.yaw)
        rz = -dx * math.sin(self.yaw) + dz * math.cos(self.yaw)
        ry = dy * math.cos(self.pitch) - rz * math.sin(self.pitch)

        scale = self.base_scale * zoom
        sx = 540.0 + rx * scale
        sy = 980.0 - ry * scale
        return (sx, sy)

    def draw_3d_box(self, draw, cx, y_min, cz, wx, hy, dz, color, cam, zoom, outline_col=None):
        """رسم مجسم مكعب ثلاثي الأبعاد بـ 3 أوجه مظللة (أعلى فاتح، واجهة متوسطة، جانب داكن)"""
        x0, x1 = cx - wx / 2.0, cx + wx / 2.0
        y0, y1 = y_min, y_min + hy
        z0, z1 = cz - dz / 2.0, cz + dz / 2.0

        p001 = self.project(x0, y0, z1, cam, zoom)
        p101 = self.project(x1, y0, z1, cam, zoom)
        p100 = self.project(x1, y0, z0, cam, zoom)
        p011 = self.project(x0, y1, z1, cam, zoom)
        p111 = self.project(x1, y1, z1, cam, zoom)
        p110 = self.project(x1, y1, z0, cam, zoom)
        p010 = self.project(x0, y1, z0, cam, zoom)

        c_front = color
        c_right = shade_rgb(color, 0.76)
        c_top = shade_rgb(color, 1.16)
        out = outline_col or shade_rgb(color, 0.52)

        draw.polygon([p001, p101, p111, p011], fill=c_front, outline=out)
        draw.polygon([p101, p100, p110, p111], fill=c_right, outline=out)
        draw.polygon([p011, p111, p110, p010], fill=c_top, outline=out)

    def draw_3d_cylinder(self, draw, cx, y_min, cz, radius, height, color, cam, zoom, alpha=255):
        """رسم أسطوانة ثلاثية الأبعاد بتدرج ضوئي وغطاء بيضاوي ثلاثي الأبعاد"""
        p_bot = self.project(cx, y_min, cz, cam, zoom)
        p_top = self.project(cx, y_min + height, cz, cam, zoom)
        rx = radius * self.base_scale * zoom
        ry = rx * math.sin(self.pitch) * 0.95

        c_main = (*color, alpha)
        c_dark = (*shade_rgb(color, 0.78), alpha)
        c_top = (*shade_rgb(color, 1.15), alpha)
        c_out = (*shade_rgb(color, 0.55), min(alpha, 220))

        draw.ellipse([p_bot[0] - rx, p_bot[1] - ry, p_bot[0] + rx, p_bot[1] + ry], fill=c_dark, outline=c_out)
        draw.rectangle([p_top[0] - rx, p_top[1], p_bot[0] + rx, p_bot[1]], fill=c_main)
        draw.rectangle([p_top[0] + rx * 0.25, p_top[1], p_bot[0] + rx, p_bot[1]], fill=c_dark)
        draw.line([(p_top[0] - rx, p_top[1]), (p_bot[0] - rx, p_bot[1])], fill=c_out, width=2)
        draw.line([(p_top[0] + rx, p_top[1]), (p_bot[0] + rx, p_bot[1])], fill=c_out, width=2)
        draw.ellipse([p_top[0] - rx, p_top[1] - ry, p_top[0] + rx, p_top[1] + ry], fill=c_top, outline=c_out)

    def draw_3d_cutaway_tank(self, draw, cx, y_min, cz, radius, height, water_h, water_col, cam, zoom):
        """رسم تانك المفاعل المقطوع ثلاثي الأبعاد (الجدار الخلفي المقوس + الأعمدة الجانبية + الماء الشفاف ثلاثي الأبعاد)"""
        p_bot = self.project(cx, y_min, cz, cam, zoom)
        p_top = self.project(cx, y_min + height, cz, cam, zoom)
        rx = radius * self.base_scale * zoom
        ry = rx * math.sin(self.pitch)

        # الجدار الفولاذي الخلفي المقوس
        draw.rectangle([p_top[0] - rx, p_top[1], p_bot[0] + rx, p_bot[1]], fill=(192, 200, 208), outline=(120, 130, 140), width=2)
        # خطوط الشبكة المعدنية داخل التانك
        for g_i in range(1, 5):
            gy = lerp(p_top[1], p_bot[1], g_i / 5.0)
            draw.line([(p_top[0] - rx, gy), (p_top[0] + rx, gy)], fill=(168, 176, 184), width=1)
        draw.ellipse([p_bot[0] - rx, p_bot[1] - ry, p_bot[0] + rx, p_bot[1] + ry], fill=(165, 175, 185), outline=(110, 120, 130), width=2)

        # الماء الشفاف ثلاثي الأبعاد داخل التانك
        if water_h > 0:
            p_wtop = self.project(cx, y_min + water_h, cz, cam, zoom)
            wrx = rx * 0.92
            wry = ry * 0.92
            draw.rectangle([p_wtop[0] - wrx, p_wtop[1], p_bot[0] + wrx, p_bot[1]], fill=water_col)
            top_w_col = (min(water_col[0] + 25, 255), min(water_col[1] + 25, 255), min(water_col[2] + 20, 255), min(water_col[3] + 20, 255))
            draw.ellipse([p_wtop[0] - wrx, p_wtop[1] - wry, p_wtop[0] + wrx, p_wtop[1] + wry], fill=top_w_col, outline=(255, 255, 255, 180), width=2)

        # الجدران الجانبية البيضاء المقطوعة
        wall_w = max(int(12 * zoom), 6)
        draw.rectangle([p_top[0] - rx - wall_w // 2, p_top[1], p_bot[0] - rx + wall_w // 2, p_bot[1]], fill=(242, 245, 248), outline=(130, 140, 150), width=2)
        draw.rectangle([p_top[0] + rx - wall_w // 2, p_top[1], p_bot[0] + rx + wall_w // 2, p_bot[1]], fill=(225, 230, 236), outline=(130, 140, 150), width=2)
        draw.arc([p_top[0] - rx, p_top[1] - ry, p_top[0] + rx, p_top[1] + ry], start=180, end=360, fill=(235, 240, 245), width=max(int(8 * zoom), 4))

    def draw_palm_tree_3d(self, draw, x, z, cam, zoom):
        p_base = self.project(x, 0, z, cam, zoom)
        p_top = self.project(x + 0.25, 2.8, z, cam, zoom)
        draw.line([p_base, p_top], fill=(135, 92, 52), width=max(int(8 * zoom), 4))
        for ang_deg in (-150, -115, -75, -35, 10, 45):
            ang = math.radians(ang_deg)
            lx = p_top[0] + math.cos(ang) * 34 * zoom
            ly = p_top[1] + math.sin(ang) * 22 * zoom + 8 * zoom
            draw.line([p_top, (lx, ly)], fill=(58, 152, 48), width=max(int(6 * zoom), 3))

    def draw_safe_callout(self, draw, target_3d, off_x, off_y, text, bg_color, cam, zoom):
        tx, ty = self.project(target_3d[0], target_3d[1], target_3d[2], cam, zoom)
        bbox = draw.textbbox((0, 0), text, font=self.font_label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 22, 13
        bw = tw + pad_x * 2
        bh = th + pad_y * 2

        # منع خروج أي لافتة خارج حدود الشاشة نهائياً!
        bx = max(bw // 2 + 24, min(1080 - bw // 2 - 24, int(tx + off_x)))
        by = max(bh // 2 + 120, min(1920 - bh // 2 - 120, int(ty + off_y)))

        draw.line([(tx, ty), (bx, by)], fill=(35, 45, 55), width=4)
        draw.ellipse([tx - 6, ty - 6, tx + 6, ty + 6], fill=(255, 255, 255), outline=(35, 45, 55), width=2)

        rect = [bx - bw // 2, by - bh // 2, bx + bw // 2, by + bh // 2]
        draw.rounded_rectangle(rect, radius=24, fill=bg_color, outline=(255, 255, 255), width=3)
        draw.text((bx - tw // 2, by - th // 2 - 2), text, font=self.font_label, fill=(255, 255, 255))

    def draw_temp_gauge(self, draw, temp_c, label="CORE TEMPERATURE"):
        card = [260, 1500, 820, 1695]
        draw.rounded_rectangle(card, radius=28, fill=(248, 246, 238), outline=(45, 55, 65), width=5)

        bar_bg = [300, 1538, 575, 1588]
        draw.rounded_rectangle(bar_bg, radius=22, fill=(228, 228, 228), outline=(55, 65, 75), width=3)

        ratio = max(0.08, min(1.0, (temp_c - 150.0) / 1050.0))
        fill_w = int((575 - 300 - 8) * ratio)
        bar_color = (230, 55, 45) if temp_c >= 700 else (45, 185, 85)
        draw.rounded_rectangle([304, 1542, 304 + fill_w, 1584], radius=18, fill=bar_color)

        t_str = f"{int(temp_c)}°C"
        draw.text((598, 1532), t_str, font=self.font_gauge_num, fill=bar_color)

        bbox = draw.textbbox((0, 0), label, font=self.font_gauge_sub)
        lw = bbox[2] - bbox[0]
        draw.text((540 - lw // 2, 1622), label, font=self.font_gauge_sub, fill=(45, 55, 65))

    def render_frame(self, seg_idx, seg_progress, global_time, current_word):
        img = Image.new("RGB", (1080, 1920), (112, 176, 232))
        draw = ImageDraw.Draw(img, "RGBA")

        seg = NUCLEAR_PLANT_SEGMENTS[seg_idx]
        ep = smoothstep(seg_progress)
        cam = (
            lerp(seg["cam_start"][0], seg["cam_end"][0], ep),
            lerp(seg["cam_start"][1], seg["cam_end"][1], ep),
            lerp(seg["cam_start"][2], seg["cam_end"][2], ep)
        )
        zoom = lerp(seg["cam_start"][3], seg["cam_end"][3], ep)

        # 1. السماء والشمس والسحب الثلاثية الأبعاد
        sun_x, sun_y = 875, 390
        for rg, ag in [(145, 35), (110, 65), (80, 110)]:
            draw.ellipse([sun_x - rg, sun_y - rg, sun_x + rg, sun_y + rg], fill=(255, 235, 130, ag))
        draw.ellipse([sun_x - 58, sun_y - 58, sun_x + 58, sun_y + 58], fill=(255, 248, 195))

        for cx0, cy0, csc in [(170, 250, 1.0), (540, 325, 1.15), (830, 175, 0.9), (95, 470, 0.85)]:
            cx = (cx0 + global_time * 9.0 * csc) % 1280 - 100
            for dx, dy, rad in [(-52, 12, 46), (0, -10, 60), (52, 10, 48), (18, 16, 44)]:
                rc = int(rad * csc)
                draw.ellipse([cx + dx * csc - rc, cy0 + dy * csc - rc, cx + dx * csc + rc, cy0 + dy * csc + rc], fill=(232, 238, 244))
                draw.ellipse([cx + dx * csc - rc, cy0 + dy * csc - rc - 5, cx + dx * csc + rc, cy0 + dy * csc + rc - 5], fill=(250, 252, 255))

        # 2. الأرض الخضراء والنهر والأشجار الثلاثية الأبعاد
        p_river_Check = self.project(0, 0, -9.5, cam, zoom)
        horizon_y = max(560, int(p_river_Check[1] - 130 * zoom))
        draw.rectangle([0, horizon_y, 1080, 1920], fill=(98, 180, 68))

        r_p1 = self.project(-45, 0, -12.5, cam, zoom)
        r_p2 = self.project(45, 0, -12.5, cam, zoom)
        r_p3 = self.project(45, 0, -7.2, cam, zoom)
        r_p4 = self.project(-45, 0, -7.2, cam, zoom)
        draw.polygon([r_p1, r_p2, r_p3, r_p4], fill=(82, 164, 198), outline=(145, 115, 75))

        # بقعة الماء الساخن والسمك في النهر (المشهد 5)
        if seg_idx in (5, 6):
            hp_c = self.project(5.5, 0, -9.5, cam, zoom)
            rx_p, ry_p = int(155 * zoom), int(42 * zoom)
            p_col = (225, 115, 75, 190) if seg_idx == 5 else (140, 175, 190, 110)
            draw.ellipse([hp_c[0] - rx_p, hp_c[1] - ry_p, hp_c[0] + rx_p, hp_c[1] + ry_p], fill=p_col)
            if seg_idx == 5:
                for fi, (fx_w, fz_w) in enumerate([(4.2, -9.6), (5.6, -9.2), (6.9, -9.7)]):
                    fp = self.project(fx_w - seg_progress * 1.2, 0.2, fz_w, cam, zoom)
                    f_col = (232, 152, 142) if seg_progress > 0.35 else (175, 190, 200)
                    fw, fh = int(28 * zoom), int(12 * zoom)
                    draw.ellipse([fp[0] - fw, fp[1] - fh, fp[0] + fw, fp[1] + fh], fill=f_col, outline=(45, 55, 65), width=2)
                    draw.polygon([(fp[0] + fw - 3, fp[1]), (fp[0] + fw + int(14 * zoom), fp[1] - fh), (fp[0] + fw + int(14 * zoom), fp[1] + fh)], fill=f_col, outline=(45, 55, 65))

        # القارب الشراعي وأشجار النخيل الثلاثية الأبعاد
        boat_x = 12.0 - (global_time * 1.4) % 24.0
        bp = self.project(boat_x, 0.2, -9.6, cam, zoom)
        bw = int(24 * zoom)
        draw.polygon([(bp[0] - bw, bp[1]), (bp[0] + bw, bp[1]), (bp[0] + int(bw * 0.7), bp[1] + int(10 * zoom)), (bp[0] - int(bw * 0.7), bp[1] + int(10 * zoom))], fill=(140, 88, 48))
        draw.polygon([(bp[0], bp[1] - int(42 * zoom)), (bp[0], bp[1] - 2), (bp[0] + int(22 * zoom), bp[1] - 2)], fill=(250, 250, 250), outline=(80, 80, 80))

        for px in (-10.5, -7.5, -4.5, 4.5, 11.5):
            self.draw_palm_tree_3d(draw, px, -6.5, cam, zoom)

        # المبنى الإداري في الخلفية
        self.draw_3d_box(draw, -1.8, 0.0, -5.2, 5.2, 2.2, 2.0, (226, 212, 182), cam, zoom)

        # 3. المنصة الخرسانية المبلطة ثلاثية الأبعاد (3D Perspective Tiled Pad)
        pad_x0, pad_x1 = -11.5, 13.5
        pad_z0, pad_z1 = -4.2, 4.8
        c_00 = self.project(pad_x0, 0, pad_z0, cam, zoom)
        c_10 = self.project(pad_x1, 0, pad_z0, cam, zoom)
        c_11 = self.project(pad_x1, 0, pad_z1, cam, zoom)
        c_01 = self.project(pad_x0, 0, pad_z1, cam, zoom)
        draw.polygon([c_00, c_10, c_11, c_01], fill=(216, 210, 197), outline=(160, 154, 142))

        for gx in range(-11, 14, 1):
            l1 = self.project(gx, 0, pad_z0, cam, zoom)
            l2 = self.project(gx, 0, pad_z1, cam, zoom)
            draw.line([l1, l2], fill=(196, 190, 178), width=1)
        for gz in range(-4, 5, 1):
            l1 = self.project(pad_x0, 0, gz, cam, zoom)
            l2 = self.project(pad_x1, 0, gz, cam, zoom)
            draw.line([l1, l2], fill=(196, 190, 178), width=1)

        # الطريق الأسفلتي ثلاثي الأبعاد في المقدمة
        rd_1 = self.project(-22, 0, 5.6, cam, zoom)
        rd_2 = self.project(22, 0, 5.6, cam, zoom)
        rd_3 = self.project(22, 0, 8.2, cam, zoom)
        rd_4 = self.project(-22, 0, 8.2, cam, zoom)
        draw.polygon([rd_1, rd_2, rd_3, rd_4], fill=(106, 112, 118), outline=(78, 84, 90))
        for rx_d in range(-18, 19, 3):
            d1 = self.project(rx_d, 0.02, 6.9, cam, zoom)
            d2 = self.project(rx_d + 1.3, 0.02, 6.9, cam, zoom)
            draw.line([d1, d2], fill=(245, 245, 245), width=max(int(5 * zoom), 3))

        # 4. قبة الاحتواء الخرسانية والحديدية المقطوعة ثلاثية الأبعاد (Stage 7+)
        if seg_idx >= 7:
            d_drop = smoothstep(seg_progress * 1.6) if seg_idx == 7 else 1.0
            dy_off = (1.0 - d_drop) * 7.0
            dc_bot = self.project(0.0, dy_off, 0.0, cam, zoom)
            dr_w = int(4.4 * self.base_scale * zoom)
            dr_h = int(7.6 * self.base_scale * zoom)
            draw.pieslice([dc_bot[0] - dr_w - 18, dc_bot[1] - dr_h - 18, dc_bot[0] + dr_w + 18, dc_bot[1] + dr_h // 3], start=180, end=360, fill=(208, 212, 216), outline=(110, 115, 120), width=3)
            draw.pieslice([dc_bot[0] - dr_w, dc_bot[1] - dr_h, dc_bot[0] + dr_w, dc_bot[1] + dr_h // 3], start=180, end=360, fill=(142, 148, 155), outline=(85, 90, 95), width=3)

        # 5. تانك المفاعل الأول ثلاثي الأبعاد (3D Primary Reactor Tank + Uranium Core + Control Rods)
        self.draw_3d_box(draw, -2.2, 0.0, 0.0, 3.2, 0.35, 2.8, (205, 200, 188), cam, zoom, outline_col=(235, 182, 35))
        w_col1 = (118, 198, 188, 195) if seg_idx >= 4 else (95, 188, 238, 195)
        self.draw_3d_cutaway_tank(draw, -2.2, 0.35, 0.0, 1.35, 5.4, 4.3, w_col1, cam, zoom)

        # الونش الأصفر ثلاثي الأبعاد في المشهد 0 و 1
        if seg_idx <= 1:
            self.draw_3d_box(draw, -3.85, 0.0, 0.2, 0.28, 6.8, 0.28, (238, 185, 38), cam, zoom)
            self.draw_3d_box(draw, -0.55, 0.0, 0.2, 0.28, 6.8, 0.28, (238, 185, 38), cam, zoom)
            self.draw_3d_box(draw, -2.2, 6.65, 0.2, 3.6, 0.32, 0.35, (238, 185, 38), cam, zoom)

        # حزمة قضبان اليورانيوم ثلاثية الأبعاد
        rod_drop = smoothstep(seg_progress * 2.2) if seg_idx == 0 else 1.0
        ry_base = lerp(4.6, 0.85, rod_drop)
        is_hot = (seg_idx == 0 and seg_progress > 0.45) or (1 <= seg_idx <= 8)
        if is_hot:
            gp = self.project(-2.2, ry_base + 1.1, 0.0, cam, zoom)
            gr = int(68 * zoom)
            draw.ellipse([gp[0] - gr, gp[1] - gr, gp[0] + gr, gp[1] + gr], fill=(255, 165, 45, 90))

        r_color = (242, 168, 55) if is_hot else (138, 96, 68)
        for rx_off in (-0.66, -0.22, 0.22, 0.66):
            self.draw_3d_box(draw, -2.2 + rx_off, ry_base, 0.0, 0.24, 2.2, 0.24, r_color, cam, zoom)
        self.draw_3d_box(draw, -2.2, ry_base + 2.2, 0.0, 1.75, 0.16, 1.0, (115, 125, 135), cam, zoom)
        self.draw_3d_box(draw, -2.2, ry_base - 0.12, 0.0, 1.75, 0.14, 1.0, (115, 125, 135), cam, zoom)

        # أعمدة التحكم السوداء والمغناطيس الكهربائي ثلاثي الأبعاد
        if seg_idx >= 2:
            if seg_idx == 2:
                c_depth = smoothstep((seg_progress - 0.35) * 1.8)
            elif seg_idx == 3:
                c_depth = 1.0 if seg_progress > 0.58 else 0.22
            else:
                c_depth = 0.55
            cy_base = lerp(4.2, 1.4, c_depth)
            for cx_off in (-0.45, 0.0, 0.45):
                self.draw_3d_cylinder(draw, -2.2 + cx_off, cy_base, 0.0, 0.11, 2.1, (68, 76, 84), cam, zoom)
                if seg_idx >= 3:
                    self.draw_3d_box(draw, -2.2 + cx_off, 5.15, 0.0, 0.34, 0.42, 0.34, (218, 55, 45), cam, zoom, outline_col=(250, 205, 45))

        # فقاعات الغليان الثلاثية الأبعاد
        if (seg_idx == 0 and seg_progress > 0.45) or seg_idx >= 1:
            for bx_o, by_s, bz_o, b_rad in self.bubbles[:16]:
                b_prog = (by_s + global_time * 0.55) % 1.0
                bp = self.project(-2.2 + bx_o, lerp(1.2, 4.4, b_prog), bz_o, cam, zoom)
                br = max(int(b_rad * 0.45 * zoom), 3)
                draw.ellipse([bp[0] - br, bp[1] - br, bp[0] + br, bp[1] + br], fill=(255, 255, 255, 205))

        # صندوق التحكم الثلاثي الأبعاد والسرينة الحمراء في المقدمة
        self.draw_3d_box(draw, -0.35, 0.0, 1.65, 0.85, 1.15, 0.75, (132, 138, 144), cam, zoom)
        self.draw_3d_cylinder(draw, -0.35, 1.15, 1.65, 0.16, 0.26, (225, 40, 40), cam, zoom)
        if seg_idx in (2, 3, 8):
            sp = self.project(-0.35, 1.3, 1.65, cam, zoom)
            sr = int((28 + 12 * abs(math.sin(global_time * 8))) * zoom)
            draw.ellipse([sp[0] - sr, sp[1] - sr, sp[0] + sr, sp[1] + sr], fill=(255, 40, 40, 110))

        # 6. التانك الثاني (Secondary Clean Water Loop) ومبادل الحرارة (Stage 4+)
        if seg_idx >= 4:
            self.draw_3d_box(draw, 1.35, 0.0, 0.0, 2.5, 0.32, 2.4, (205, 200, 188), cam, zoom)
            self.draw_3d_cutaway_tank(draw, 1.35, 0.32, 0.0, 1.05, 5.4, 4.1, (105, 195, 242, 195), cam, zoom)

            # أنابيب الربط الحمراء والزرقاء وطلمبة المياه
            p_h1 = self.project(-0.95, 2.9, 0.2, cam, zoom)
            p_h2 = self.project(0.35, 2.9, 0.2, cam, zoom)
            p_c1 = self.project(-0.95, 1.4, 0.2, cam, zoom)
            p_c2 = self.project(0.35, 1.4, 0.2, cam, zoom)
            draw.line([p_h1, p_h2], fill=(238, 102, 52), width=max(int(14 * zoom), 6))
            draw.line([p_c1, p_c2], fill=(72, 162, 232), width=max(int(14 * zoom), 6))

            pmp = self.project(-0.3, 1.4, 0.3, cam, zoom)
            pr = int(14 * zoom)
            draw.ellipse([pmp[0] - pr, pmp[1] - pr, pmp[0] + pr, pmp[1] + pr], fill=(55, 65, 75), outline=(255, 255, 255), width=2)
            if seg_idx == 8:
                draw.line([(pmp[0] - pr, pmp[1] - pr), (pmp[0] + pr, pmp[1] + pr)], fill=(235, 45, 45), width=4)
                draw.line([(pmp[0] + pr, pmp[1] - pr), (pmp[0] - pr, pmp[1] + pr)], fill=(235, 45, 45), width=4)

        # 7. ماسورة البخار + التوربينة الدوارة 3D + المولد الأخضر 3D + عمود الإنارة (Stage 1+)
        if seg_idx >= 1:
            src_x = 1.35 if seg_idx >= 4 else -2.2
            sp1 = self.project(src_x, 5.75, 0.0, cam, zoom)
            sp2 = self.project(src_x, 6.55, 0.0, cam, zoom)
            sp3 = self.project(4.4, 6.55, 0.3, cam, zoom)
            sp4 = self.project(4.4, 1.65, 0.3, cam, zoom)
            draw.line([sp1, sp2, sp3, sp4], fill=(208, 216, 224), width=max(int(15 * zoom), 6), joint="curve")

            # قاعدة التوربينة والشفرات الثلاثية الأبعاد الدوارة
            self.draw_3d_box(draw, 4.4, 0.0, 0.3, 2.2, 0.55, 1.5, (162, 170, 178), cam, zoom)
            tb_c = self.project(4.4, 1.25, 0.3, cam, zoom)
            tb_w, tb_h = int(46 * zoom), int(26 * zoom)
            draw.polygon([
                (tb_c[0] - tb_w, tb_c[1] - tb_h),
                (tb_c[0] + tb_w, tb_c[1] - tb_h),
                (tb_c[0] + tb_w - 8, tb_c[1] + tb_h),
                (tb_c[0] - tb_w - 8, tb_c[1] + tb_h)
            ], fill=(185, 195, 205), outline=(95, 105, 115), width=2)

            spin = global_time * 14.0
            for b_i in range(5):
                bx_b = tb_c[0] - tb_w + int((b_i + 0.5) * (2 * tb_w / 5))
                bh_b = int(tb_h * (0.35 + 0.65 * abs(math.sin(spin + b_i * 0.85))))
                draw.polygon([
                    (bx_b - int(8 * zoom), tb_c[1] - bh_b),
                    (bx_b + int(8 * zoom), tb_c[1]),
                    (bx_b - int(8 * zoom), tb_c[1] + bh_b)
                ], fill=(246, 249, 252), outline=(110, 120, 130))

            # المولد الكهربائي الأخضر الثلاثي الأبعاد
            self.draw_3d_box(draw, 6.5, 0.0, 0.3, 1.8, 1.95, 1.6, (66, 178, 140), cam, zoom)

            # عمود الإنارة المضيء
            lp_bot = self.project(8.2, 0.0, 1.2, cam, zoom)
            lp_top = self.project(8.2, 2.7, 1.2, cam, zoom)
            draw.line([lp_bot, lp_top], fill=(68, 74, 80), width=max(int(5 * zoom), 3))
            lr = int(16 * zoom)
            draw.ellipse([lp_top[0] - lr * 2, lp_top[1] - lr * 2, lp_top[0] + lr * 2, lp_top[1] + lr * 2], fill=(255, 240, 120, 95))
            draw.ellipse([lp_top[0] - lr, lp_top[1] - lr, lp_top[0] + lr, lp_top[1] + lr], fill=(255, 248, 160), outline=(120, 110, 60), width=2)

        # 8. المكثف (Condenser) وبرج التبريد المخروطي ثلاثي الأبعاد (Stage 5 & 6+)
        if seg_idx >= 5:
            self.draw_3d_box(draw, 4.6, 0.0, -1.6, 1.6, 1.25, 1.4, (142, 188, 220), cam, zoom)
            rp1 = self.project(4.6, 0.4, -2.3, cam, zoom)
            rp2 = self.project(5.2, 0.2, -7.5, cam, zoom)
            draw.line([rp1, rp2], fill=(72, 162, 232), width=max(int(8 * zoom), 4))
            draw.line([(rp1[0] + 10, rp1[1]), (rp2[0] + 10, rp2[1])], fill=(235, 95, 52), width=max(int(8 * zoom), 4))

        if seg_idx >= 6:
            # برج التبريد ثلاثي الأبعاد (3D Hyperboloid Cooling Tower)
            t_alpha = 165 if seg_idx == 6 else 255
            self.draw_3d_cylinder(draw, 9.6, 0.0, -1.2, 2.35, 0.45, (125, 185, 222), cam, zoom, alpha=255)
            p_tb = self.project(9.6, 0.45, -1.2, cam, zoom)
            p_tm = self.project(9.6, 4.2, -1.2, cam, zoom)
            p_tt = self.project(9.6, 6.4, -1.2, cam, zoom)
            rb = int(2.2 * self.base_scale * zoom)
            rm = int(1.35 * self.base_scale * zoom)
            rt = int(1.55 * self.base_scale * zoom)
            draw.polygon([
                (p_tb[0] - rb, p_tb[1]),
                (p_tm[0] - rm, p_tm[1]),
                (p_tt[0] - rt, p_tt[1]),
                (p_tt[0] + rt, p_tt[1]),
                (p_tm[0] + rm, p_tm[1]),
                (p_tb[0] + rb, p_tb[1])
            ], fill=(216, 210, 198, t_alpha), outline=(135, 130, 120))
            ry_t = int(rt * math.sin(self.pitch))
            draw.ellipse([p_tt[0] - rt, p_tt[1] - ry_t, p_tt[0] + rt, p_tt[1] + ry_t], fill=(165, 160, 150, t_alpha), outline=(120, 115, 105))

            # سحابة بخار الماء النقي H2O أعلى برج التبريد
            for s_i in range(5):
                sp_r = (s_i * 0.2 + global_time * 0.35) % 1.0
                sc_p = self.project(9.6 + math.sin(sp_r * 5) * 0.35, 6.6 + sp_r * 3.2, -1.2, cam, zoom)
                sr = int((26 + sp_r * 34) * zoom)
                draw.ellipse([sc_p[0] - sr, sc_p[1] - sr, sc_p[0] + sr, sc_p[1] + sr], fill=(255, 255, 255, int(215 * (1.0 - sp_r * 0.6))))

        # 9. المولدات الاحتياطية الصفراء وتانك الجاذبية المرتفع 3D (Stage 8+)
        if seg_idx >= 8:
            self.draw_3d_box(draw, -5.8, 0.0, 0.2, 1.5, 1.5, 1.3, (238, 195, 52), cam, zoom)
            self.draw_3d_box(draw, -4.6, 0.0, 0.2, 1.1, 1.15, 1.1, (222, 178, 42), cam, zoom)
            self.draw_3d_cylinder(draw, -5.2, 4.8, -0.4, 1.1, 1.6, (125, 188, 228), cam, zoom)
            leg_top = self.project(-5.2, 4.8, -0.4, cam, zoom)
            leg_bot = self.project(-5.2, 0.3, -0.4, cam, zoom)
            draw.line([(leg_top[0] - int(22 * zoom), leg_top[1]), (leg_bot[0] - int(22 * zoom), leg_bot[1])], fill=(90, 98, 106), width=4)
            draw.line([(leg_top[0] + int(22 * zoom), leg_top[1]), (leg_bot[0] + int(22 * zoom), leg_bot[1])], fill=(90, 98, 106), width=4)

        # 10. حوض الوقود النووي المستعمل وتوهج شيرينكوف الأزرق 3D (Stage 9+)
        if seg_idx >= 9:
            self.draw_3d_box(draw, -8.8, 0.0, 1.4, 2.6, 1.7, 2.2, (222, 228, 234), cam, zoom)
            self.draw_3d_box(draw, -8.8, 0.2, 1.4, 2.2, 1.45, 1.8, (75, 178, 242), cam, zoom)
            cp = self.project(-8.8, 1.2, 1.4, cam, zoom)
            cr = int(42 * zoom)
            draw.ellipse([cp[0] - cr, cp[1] - cr, cp[0] + cr, cp[1] + cr], fill=(120, 228, 255, 145))

        # 11. اللافتات التوضيحية والمؤشرات الحرارية (Safe Callouts & Gauges)
        if seg_idx == 0:
            self.draw_safe_callout(draw, (-2.2, 1.8, 0.0), 210, -70, "URANIUM FUEL", (215, 132, 42), cam, zoom)
            self.draw_safe_callout(draw, (-3.2, 1.2, 0.0), -180, 90, "WATER TANK", (92, 155, 208), cam, zoom)
        elif seg_idx == 1:
            self.draw_safe_callout(draw, (-2.2, 5.8, 0.0), -170, -45, "STEAM", (125, 152, 172), cam, zoom)
            self.draw_safe_callout(draw, (4.4, 1.4, 0.3), -110, -125, "TURBINE", (118, 135, 150), cam, zoom)
            self.draw_safe_callout(draw, (6.5, 1.9, 0.3), 0, -135, "GENERATOR", (62, 168, 130), cam, zoom)
        elif seg_idx == 2:
            t_val = lerp(468, 1200, seg_progress / 0.48) if seg_progress < 0.48 else lerp(1200, 300, (seg_progress - 0.48) / 0.52)
            self.draw_temp_gauge(draw, t_val, "CORE TEMPERATURE")
            if seg_progress > 0.42:
                self.draw_safe_callout(draw, (-2.0, 3.2, 0.0), 210, -45, "CONTROL RODS", (68, 78, 88), cam, zoom)
        elif seg_idx == 3:
            self.draw_safe_callout(draw, (-2.0, 5.2, 0.0), 215, -35, "ELECTROMAGNETS", (215, 55, 45), cam, zoom)
        elif seg_idx == 4:
            self.draw_safe_callout(draw, (-0.3, 2.0, 0.2), 0, 175, "CLOSED LOOP", (215, 132, 42), cam, zoom)
            self.draw_safe_callout(draw, (1.35, 3.2, 0.0), 195, -105, "SECONDARY LOOP", (78, 158, 215), cam, zoom)
        elif seg_idx == 5:
            self.draw_safe_callout(draw, (4.6, 1.3, -1.6), -150, -90, "STEAM -> WATER", (78, 158, 215), cam, zoom)
            if seg_progress > 0.42:
                self.draw_temp_gauge(draw, 70, "RIVER WATER TEMP")
        elif seg_idx == 6:
            self.draw_safe_callout(draw, (9.6, 3.6, -1.2), -210, -35, "COOLING TOWER", (138, 132, 122), cam, zoom)
            self.draw_safe_callout(draw, (9.6, 7.6, -1.2), -150, -45, "PURE H2O VAPOR", (78, 158, 215), cam, zoom)
        elif seg_idx == 7:
            self.draw_safe_callout(draw, (0.0, 7.5, 0.0), 0, -85, "CONTAINMENT DOME (+1m)", (108, 115, 122), cam, zoom)
        elif seg_idx == 8:
            self.draw_temp_gauge(draw, lerp(745, 1064, min(seg_progress * 1.5, 1.0)), "CORE TEMPERATURE")
            self.draw_safe_callout(draw, (-5.8, 1.4, 0.2), -110, -125, "BACKUP GENERATORS", (212, 160, 36), cam, zoom)
            self.draw_safe_callout(draw, (-5.2, 5.5, -0.4), -70, -105, "GRAVITY WATER TANK", (78, 158, 215), cam, zoom)
        elif seg_idx == 9:
            self.draw_safe_callout(draw, (-8.8, 1.4, 1.4), 135, -135, "SPENT FUEL POOL", (58, 146, 214), cam, zoom)
        elif seg_idx == 10:
            c_box = [125, 1145, 955, 1635]
            draw.rounded_rectangle(c_box, radius=32, fill=(250, 246, 235), outline=(45, 55, 65), width=5)
            draw.rounded_rectangle([235, 1320, 302, 1408], radius=12, fill=(125, 135, 145), outline=(40, 45, 50), width=4)
            draw.ellipse([345, 1312, 405, 1368], fill=(235, 65, 55), outline=(140, 30, 25), width=3)
            draw.rounded_rectangle([340, 1348, 410, 1408], radius=18, fill=(235, 65, 55), outline=(140, 30, 25), width=3)
            draw.text((200, 1455), "1 FUEL PELLET", font=self.font_card, fill=(40, 45, 50))
            draw.text((515, 1330), "=", font=self.font_word, fill=(235, 165, 40))
            for cx_c, cy_c in [(690, 1385), (745, 1385), (800, 1385), (715, 1340), (770, 1340), (742, 1295)]:
                draw.regular_polygon((cx_c, cy_c, 34), n_sides=6, fill=(55, 60, 65), outline=(25, 30, 35))
            draw.text((645, 1455), "1 TON OF COAL", font=self.font_card, fill=(40, 45, 50))
        elif seg_idx == 11:
            for c_x, c_y0, c_s, c_col in self.confetti:
                cy_now = (c_y0 + seg_progress * 950) % 1920
                cx_now = c_x + math.sin(global_time * 5 + c_x) * 18
                draw.rectangle([cx_now - c_s, cy_now - c_s * 1.6, cx_now + c_s, cy_now + c_s * 1.6], fill=c_col)

        # 12. الكابشن العلوي كلمة بكلمة (Top Center Word-by-Word Pop Caption)
        if current_word:
            w_text = current_word.upper()
            bbox = draw.textbbox((0, 0), w_text, font=self.font_word)
            tw = bbox[2] - bbox[0]
            wx_pos = (1080 - tw) // 2
            wy_pos = 355

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

    clean_title = f"{title[:65]} #nuclear #science #shorts"[:95]

    body = {
        "snippet": {
            "title": clean_title,
            "description": f"{title}\n\n3D Animated Explainer: How a Nuclear Power Plant Works.\n#engineering #science #howitworks #nuclearpower #shorts",
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
    title = "How to Build a Nuclear Power Plant Step-by-Step!"
    font_path = ensure_english_font()
    renderer = True3DIsometricRenderer(font_path)

    print("🎙️ Step 1: Generating 100% Consistent English Voiceover & SFX (Zero Wait)...", flush=True)
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

    print("🎬 Step 2: Rendering 3D Isometric Animation Stream at 30 FPS...", flush=True)
    fps = 30
    raw_video = "raw_3d_iso.mp4"
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
        print(f"  ✓ Rendered 3D Stage {seg_idx + 1}/12", flush=True)

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()

    final_video = "final_short.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_video,
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.005",
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
