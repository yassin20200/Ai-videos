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
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-AndrewMultilingualNeural").strip() or "en-US-AndrewMultilingualNeural"

YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"

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

NUCLEAR_PLANT_SEGMENTS = [
    {
        "id": 0,
        "sfx": "splash",
        "narration": "If you drop uranium into a tank of water, the uranium gets hot, and you have a nuclear reactor."
    },
    {
        "id": 1,
        "sfx": "turbine",
        "narration": "But hot water doesn't make electricity. So you let it boil, and use steam to spin a turbine connected to a generator."
    },
    {
        "id": 2,
        "sfx": "alarm",
        "narration": "However, uranium keeps getting hotter and hotter. So you slide control rods between the fuel to absorb the reaction and cool it down."
    },
    {
        "id": 3,
        "sfx": "clunk",
        "narration": "In an emergency, you need to stop it fast. So you hang the rods above the core on electromagnets. If power cuts out, they drop right in."
    },
    {
        "id": 4,
        "sfx": "bubbles",
        "narration": "But water touching uranium gets radioactive, and right now it spins your turbine. So you seal it in a closed loop to boil clean water in a second loop."
    },
    {
        "id": 5,
        "sfx": "splash",
        "narration": "Next, you condense the steam back into water to reuse it. You can cool it with river water, but the river heats up enough to cook the fish."
    },
    {
        "id": 6,
        "sfx": "whoosh",
        "narration": "So you build a giant cooling tower. Hot water rains down inside, air carries heat up, and that cloud on top is just pure water vapor."
    },
    {
        "id": 7,
        "sfx": "clunk",
        "narration": "If anything leaks, radiation could escape. So you build a steel and concrete containment dome over a meter thick around the reactor."
    },
    {
        "id": 8,
        "sfx": "alarm",
        "narration": "If the pumps fail, the core will overheat. So you add backup generators, and a high water tank that floods the core by gravity alone."
    },
    {
        "id": 9,
        "sfx": "bubbles",
        "narration": "Used nuclear fuel stays hot for years, so you submerge it in a deep water pool where it glows bright blue."
    },
    {
        "id": 10,
        "sfx": "pop",
        "narration": "One tiny uranium fuel pellet, the size of a gummy bear, produces as much electricity as an entire ton of coal."
    },
    {
        "id": 11,
        "sfx": "cheer",
        "narration": "And congratulations! You just built a nuclear power plant."
    }
]

# قفل محرك الصوت المختار في المرحلة 0 لضمان ثبات نفس صوت المتحدث 100% في جميع المراحل الـ 12
LOCKED_VOICE_ENGINE = None


def ensure_playwright_chromium():
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("📦 Installing Playwright & Chromium for 3D WebGL Rendering...", flush=True)
        subprocess.run(["pip", "install", "-q", "playwright"], check=True)
        subprocess.run(["playwright", "install", "chromium"], check=True)


def generate_gemini_puck_voice_with_retry(narration_text, dst_wav):
    """
    توليد الصوت البشري الأمريكي الموحد (Puck) عبر Gemini 2.5 Native TTS
    مع انتظار ذكي تلقائي عند الوصول لحد الطلبات في الدقيقة (429) لضمان عدم تغير الصوت أبداً!
    """
    if not GEMINI_API_KEY:
        return False

    director_prompt = (
        "Speak as an engaging, clear, upbeat American science explainer YouTuber (like Zack D. Films), "
        "keeping the exact same consistent voice and brisk natural pacing:\n"
        f"{narration_text}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_API_KEY}"
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

    for attempt in range(5):
        try:
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
                                time.sleep(4.2)  # احترام حد الطلبات في الدقيقة لضمان ثبات الصوت في كل المراحل
                                return True
            elif r.status_code == 429:
                wait_sec = 14 + attempt * 6
                print(f"⏳ انتظار {wait_sec} ثانية لتجديد حصة الدقيقة في Gemini TTS للحفاظ على نفس الصوت...", flush=True)
                time.sleep(wait_sec)
            else:
                break
        except Exception:
            time.sleep(3)

    return False


def generate_edge_tts_voice(narration_text, dst_mp3):
    for v_name in [ENGLISH_VOICE, "en-US-AndrewMultilingualNeural", "en-US-ChristopherNeural", "en-US-GuyNeural"]:
        for attempt in range(2):
            try:
                subprocess.run([
                    "edge-tts", "--voice", v_name, "--rate=+8%",
                    "--text", narration_text, "--write-media", dst_mp3
                ], check=True, timeout=30, stderr=subprocess.DEVNULL)
                if os.path.exists(dst_mp3) and os.path.getsize(dst_mp3) > 1000:
                    return True
            except Exception:
                time.sleep(1)
    return False


def generate_google_translate_tts(narration_text, dst_mp3):
    encoded = urllib.parse.quote(narration_text)
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en&q={encoded}"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    with open(dst_mp3, "wb") as f:
        f.write(r.content)
    return os.path.exists(dst_mp3) and os.path.getsize(dst_mp3) > 500


def build_segment_audio(seg_idx, segment, out_wav):
    global LOCKED_VOICE_ENGINE
    text = segment["narration"]
    sfx_key = segment["sfx"]

    raw_voice = f"seg_raw_{seg_idx}.wav"
    trimmed_voice = f"seg_trim_{seg_idx}.wav"
    sfx_ogg = f"seg_sfx_{seg_idx}.ogg"

    voice_ok = False

    # اختيار محرك الصوت في المرحلة الأولى وقفله لجميع المراحل الـ 12 لضمان عدم تغير صوت المتحدث أبداً!
    if LOCKED_VOICE_ENGINE is None:
        if generate_gemini_puck_voice_with_retry(text, raw_voice):
            LOCKED_VOICE_ENGINE = "gemini_puck"
            voice_ok = True
            print("🎙️ Locked Voice Engine: Gemini 2.5 Native Human Voice (Puck) for all 12 stages!", flush=True)
        elif generate_edge_tts_voice(text, raw_voice):
            LOCKED_VOICE_ENGINE = "edge_tts"
            voice_ok = True
            print("🎙️ Locked Voice Engine: Microsoft Studio Narrator for all 12 stages!", flush=True)
        else:
            generate_google_translate_tts(text, raw_voice)
            LOCKED_VOICE_ENGINE = "gtts"
            voice_ok = True
            print("🎙️ Locked Voice Engine: Standard English TTS for all 12 stages!", flush=True)
    else:
        if LOCKED_VOICE_ENGINE == "gemini_puck":
            voice_ok = generate_gemini_puck_voice_with_retry(text, raw_voice)
        if not voice_ok and LOCKED_VOICE_ENGINE in ("edge_tts", "gemini_puck"):
            voice_ok = generate_edge_tts_voice(text, raw_voice)
        if not voice_ok:
            voice_ok = generate_google_translate_tts(text, raw_voice)

    warm_eq = "highpass=f=80,equalizer=f=185:width_type=o:width=1.5:g=2.4,equalizer=f=3800:width_type=o:width=2.0:g=1.8"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", raw_voice,
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


THREEJS_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@800;900&display=swap" rel="stylesheet">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 1080px; height: 1920px; overflow: hidden; background: #6eb1e8; font-family: 'Montserrat', sans-serif; }
  canvas { display: none; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
<canvas id="webgl-canvas" width="1080" height="1920"></canvas>
<canvas id="hud-canvas" width="1080" height="1920"></canvas>
<canvas id="final-canvas" width="1080" height="1920"></canvas>
<script>
const W = 1080, H = 1920;
const webglCanvas = document.getElementById('webgl-canvas');
const hudCanvas = document.getElementById('hud-canvas');
const finalCanvas = document.getElementById('final-canvas');
const ctx = hudCanvas.getContext('2d');
const finalCtx = finalCanvas.getContext('2d');

const renderer = new THREE.WebGLRenderer({ canvas: webglCanvas, antialias: true, preserveDrawingBuffer: true, alpha: false });
renderer.setSize(W, H);
renderer.setClearColor(0x6eb1e8, 1);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x6eb1e8);
const camera = new THREE.PerspectiveCamera(38, W / H, 0.5, 400);

const hemiLight = new THREE.HemisphereLight(0xffffff, 0x688850, 0.80);
hemiLight.position.set(0, 50, 0);
scene.add(hemiLight);

const dirLight = new THREE.DirectionalLight(0xfff8e8, 0.85);
dirLight.position.set(22, 42, 28);
dirLight.castShadow = true;
dirLight.shadow.mapSize.width = 2048;
dirLight.shadow.mapSize.height = 2048;
scene.add(dirLight);

function mat(color, opts = {}) {
  return new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.45, metalness: 0.1 }, opts));
}

// 3D Sun & Fluffy 3D Clouds in Sky
const sunGroup = new THREE.Group();
const sunCore = new THREE.Mesh(new THREE.SphereGeometry(3.2, 24, 24), new THREE.MeshBasicMaterial({ color: 0xfff5be }));
sunGroup.add(sunCore);
[4.6, 6.2, 8.0].forEach((r, idx) => {
  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(r, 24, 24),
    new THREE.MeshBasicMaterial({ color: 0xffe885, transparent: true, opacity: 0.28 - idx * 0.07 })
  );
  sunGroup.add(halo);
});
sunGroup.position.set(14, 22, -35);
scene.add(sunGroup);

const clouds3D = [];
function createCloud3D(x, y, z, scale) {
  const cg = new THREE.Group();
  const cMat = mat(0xfafcff, { roughness: 0.9 });
  [[-1.6, 0, 0, 1.3], [0, 0.5, 0.2, 1.7], [1.6, 0.1, 0, 1.4], [0.5, -0.3, 0.4, 1.2]].forEach(([dx, dy, dz, r]) => {
    const puff = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 16), cMat);
    puff.position.set(dx, dy, dz);
    cg.add(puff);
  });
  cg.scale.set(scale, scale, scale * 0.6);
  cg.position.set(x, y, z);
  scene.add(cg);
  clouds3D.push({ mesh: cg, baseX: x, speed: 0.4 * scale });
}
createCloud3D(-14, 21, -32, 1.5);
createCloud3D(-1, 18, -30, 1.7);
createCloud3D(11, 25, -34, 1.3);
createCloud3D(-18, 14, -28, 1.2);

// 1. Ground, Tiled Pad, Road & River
const grass = new THREE.Mesh(new THREE.BoxGeometry(180, 2, 180), mat(0x5fb43c, { roughness: 0.8 }));
grass.position.set(0, -1, 0);
grass.receiveShadow = true;
scene.add(grass);

const river = new THREE.Mesh(new THREE.BoxGeometry(180, 1.6, 12), mat(0x529ec2, { roughness: 0.3 }));
river.position.set(0, -0.45, -18);
scene.add(river);

const riverBank1 = new THREE.Mesh(new THREE.BoxGeometry(180, 2.05, 1.2), mat(0x9b7a4a));
riverBank1.position.set(0, -0.65, -11.8);
scene.add(riverBank1);

// Hot River Plume & 3D Fish (Stage 5)
const plumeGroup = new THREE.Group();
const plumeMesh = new THREE.Mesh(new THREE.CylinderGeometry(4.5, 4.5, 0.2, 32), mat(0xd47254, { transparent: true, opacity: 0.78 }));
plumeMesh.scale.set(1.8, 1, 0.65);
plumeMesh.position.set(8, 0.4, -16.5);
plumeGroup.add(plumeMesh);

const fishList = [];
for (let i = 0; i < 3; i++) {
  const fg = new THREE.Group();
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.55, 16, 12), mat(0xa8b8c0));
  body.scale.set(1.8, 0.75, 0.4);
  const tail = new THREE.Mesh(new THREE.ConeGeometry(0.45, 0.7, 3), mat(0xa8b8c0));
  tail.rotation.z = Math.PI / 2;
  tail.position.set(1.0, 0, 0);
  const eye = new THREE.Mesh(new THREE.SphereGeometry(0.1, 8, 8), mat(0x111111));
  eye.position.set(-0.55, 0.1, 0.2);
  fg.add(body, tail, eye);
  fg.position.set(5.5 + i * 2.4, 0.6, -16.2 + (i % 2) * 0.9);
  plumeGroup.add(fg);
  fishList.push({ group: fg, body, tail, baseX: fg.position.x });
}
scene.add(plumeGroup);

// 3D Sailboat
const boatGroup = new THREE.Group();
const hull = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.5, 0.5, 4), mat(0x8a5229));
hull.rotation.y = Math.PI / 4;
hull.scale.set(1.8, 1, 0.8);
const sail = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.5, 3), mat(0xffffff));
sail.position.set(0, 1.4, 0);
boatGroup.add(hull, sail);
boatGroup.position.set(14, 0.5, -17);
scene.add(boatGroup);

// 3D Palm Trees
function createPalmTree(x, z) {
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.28, 3.6, 8), mat(0x8c6239));
  trunk.position.y = 1.8;
  g.add(trunk);
  for (let i = 0; i < 6; i++) {
    const leaf = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.08, 0.35), mat(0x3f9e33));
    leaf.position.set(Math.cos(i * Math.PI / 3) * 0.7, 3.5, Math.sin(i * Math.PI / 3) * 0.7);
    leaf.rotation.y = -i * Math.PI / 3;
    leaf.rotation.z = -0.35;
    g.add(leaf);
  }
  g.position.set(x, 0, z);
  scene.add(g);
}
[-14, -10, -6, 6, 15].forEach(x => createPalmTree(x, -10.5));

// Power Plant Office Building
const officeGroup = new THREE.Group();
const officeBody = new THREE.Mesh(new THREE.BoxGeometry(7.5, 3.2, 3.2), mat(0xdfd0b2));
officeBody.position.y = 1.6;
officeGroup.add(officeBody);
for (let i = -2; i <= 2; i++) {
  const win = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.1, 0.1), mat(0x6b9bc3));
  win.position.set(i * 1.3, 1.7, 1.61);
  officeGroup.add(win);
}
officeGroup.position.set(-2.5, 0, -7.2);
scene.add(officeGroup);

// Tiled Concrete Pad
const padCanvas = document.createElement('canvas');
padCanvas.width = 512; padCanvas.height = 512;
const pctx = padCanvas.getContext('2d');
pctx.fillStyle = '#d8d2c5';
pctx.fillRect(0, 0, 512, 512);
pctx.strokeStyle = '#bcb5a6';
pctx.lineWidth = 3;
for (let i = 0; i <= 512; i += 32) {
  pctx.beginPath(); pctx.moveTo(i, 0); pctx.lineTo(i, 512); pctx.stroke();
  pctx.beginPath(); pctx.moveTo(0, i); pctx.lineTo(512, i); pctx.stroke();
}
const padTex = new THREE.CanvasTexture(padCanvas);
padTex.wrapS = padTex.wrapT = THREE.RepeatWrapping;
padTex.repeat.set(4, 2.5);
const padMesh = new THREE.Mesh(new THREE.BoxGeometry(34, 0.3, 16), new THREE.MeshStandardMaterial({ map: padTex, roughness: 0.7 }));
padMesh.position.set(3, 0.15, 0.5);
padMesh.receiveShadow = true;
scene.add(padMesh);

// Asphalt Road
const roadGroup = new THREE.Group();
const roadMesh = new THREE.Mesh(new THREE.BoxGeometry(60, 0.22, 4.4), mat(0x70757a, { roughness: 0.8 }));
roadGroup.add(roadMesh);
for (let i = -26; i <= 26; i += 4) {
  const dash = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.25, 0.22), mat(0xf5f5f5));
  dash.position.set(i, 0.02, 0);
  roadGroup.add(dash);
}
roadGroup.position.set(2, 0.12, 9.2);
roadGroup.rotation.y = -0.22;
scene.add(roadGroup);

// 2. Primary Reactor Tank (3D Cutaway Cylinder)
const reactorGroup = new THREE.Group();
reactorGroup.position.set(-2.5, 0.3, 1.0);
scene.add(reactorGroup);

const rBase = new THREE.Mesh(new THREE.BoxGeometry(4.8, 0.5, 4.2), mat(0xd2cdc0));
rBase.position.y = 0.25;
reactorGroup.add(rBase);
const rBaseTrim = new THREE.Mesh(new THREE.BoxGeometry(4.9, 0.14, 4.3), mat(0xeab826));
rBaseTrim.position.y = 0.08;
reactorGroup.add(rBaseTrim);

const rBackWall = new THREE.Mesh(
  new THREE.CylinderGeometry(2.0, 2.0, 8.2, 32, 1, true, Math.PI * 0.55, Math.PI * 0.9),
  mat(0xcfd6dc, { side: THREE.DoubleSide, metalness: 0.25, roughness: 0.35 })
);
rBackWall.position.y = 4.6;
reactorGroup.add(rBackWall);

const pillarL = new THREE.Mesh(new THREE.BoxGeometry(0.32, 8.2, 0.4), mat(0xeef2f6));
pillarL.position.set(-1.95, 4.6, 0.2);
const pillarR = pillarL.clone();
pillarR.position.set(1.95, 4.6, 0.2);
const topCap = new THREE.Mesh(new THREE.CylinderGeometry(2.15, 2.15, 0.35, 32), mat(0xdce2e8));
topCap.position.y = 8.75;
reactorGroup.add(pillarL, pillarR, topCap);

const waterMat1 = new THREE.MeshStandardMaterial({ color: 0x5ab9ea, transparent: true, opacity: 0.68, roughness: 0.15 });
const waterMesh1 = new THREE.Mesh(new THREE.CylinderGeometry(1.88, 1.88, 6.8, 32), waterMat1);
waterMesh1.position.y = 3.9;
reactorGroup.add(waterMesh1);

// 3D Yellow Gantry Crane
const craneGroup = new THREE.Group();
const cLegL = new THREE.Mesh(new THREE.BoxGeometry(0.35, 10.6, 0.35), mat(0xe8b428));
cLegL.position.set(-2.55, 5.3, 0.5);
const cLegR = cLegL.clone();
cLegR.position.set(2.55, 5.3, 0.5);
const cBeam = new THREE.Mesh(new THREE.BoxGeometry(5.6, 0.45, 0.5), mat(0xe8b428));
cBeam.position.set(0, 10.5, 0.5);
craneGroup.add(cLegL, cLegR, cBeam);
reactorGroup.add(craneGroup);

// 3D Uranium Fuel Bundle
const fuelGroup = new THREE.Group();
const fuelRods = [];
for (let gx = -1.5; gx <= 1.5; gx += 1) {
  for (let gz = -0.5; gz <= 0.5; gz += 1) {
    const rod = new THREE.Mesh(new THREE.BoxGeometry(0.28, 3.2, 0.28), mat(0x885c42));
    rod.position.set(gx * 0.55, 0, gz * 0.55);
    fuelGroup.add(rod);
    fuelRods.push(rod);
  }
}
const plateTop = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.22, 1.4), mat(0x707880));
plateTop.position.y = 1.65;
const plateBot = plateTop.clone();
plateBot.position.y = -1.65;
fuelGroup.add(plateTop, plateBot);
reactorGroup.add(fuelGroup);

const coreGlowLight = new THREE.PointLight(0xff8c1a, 0, 9);
coreGlowLight.position.set(0, 2.5, 1.2);
reactorGroup.add(coreGlowLight);

// 3D Control Rods & Electromagnets
const ctrlGroup = new THREE.Group();
const magGroup = new THREE.Group();
for (let i = -1; i <= 1; i++) {
  const cRod = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 3.2, 16), mat(0x454c54, { metalness: 0.5 }));
  cRod.position.set(i * 0.65, 0, 0);
  ctrlGroup.add(cRod);

  const mag = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.55, 0.48), mat(0xd83428));
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.50, 0.14, 0.50), mat(0xf6c834));
  mag.add(stripe);
  mag.position.set(i * 0.65, 7.8, 0);
  magGroup.add(mag);
}
reactorGroup.add(ctrlGroup, magGroup);

// 3D Front Control Box with Red Siren
const ctrlBoxGroup = new THREE.Group();
const cBox = new THREE.Mesh(new THREE.BoxGeometry(1.3, 1.7, 1.1), mat(0x80868c));
cBox.position.y = 0.85;
const panelFace = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.5, 0.1), mat(0x3a4840));
panelFace.position.set(0, 1.15, 0.52);
ctrlBoxGroup.add(cBox, panelFace);
for (let i = -1; i <= 1; i++) {
  const btn = new THREE.Mesh(new THREE.SphereGeometry(0.11, 12, 12), mat(0x3ed658));
  btn.position.set(i * 0.28, 1.15, 0.58);
  ctrlBoxGroup.add(btn);
}
const sirenMat = mat(0xd82222, { emissive: 0xaa0000, emissiveIntensity: 0.4 });
const siren = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.22, 0.35, 16), sirenMat);
siren.position.set(0, 1.85, 0);
ctrlBoxGroup.add(siren);
ctrlBoxGroup.position.set(2.35, 0, 2.2);
reactorGroup.add(ctrlBoxGroup);

// 3D Bubbles
const bubbles3D = [];
const bubbleGeo = new THREE.SphereGeometry(0.14, 12, 12);
const bubbleMat = mat(0xffffff, { transparent: true, opacity: 0.82 });
for (let i = 0; i < 26; i++) {
  const b = new THREE.Mesh(bubbleGeo, bubbleMat);
  b.userData = {
    x: (Math.random() - 0.5) * 2.4,
    z: (Math.random() - 0.5) * 1.2,
    seed: Math.random(),
    speed: 0.45 + Math.random() * 0.35
  };
  reactorGroup.add(b);
  bubbles3D.push(b);
}

// 3. Secondary Clean Water Tank
const secTankGroup = new THREE.Group();
secTankGroup.position.set(2.5, 0.3, 1.0);
scene.add(secTankGroup);

const sBackWall = new THREE.Mesh(
  new THREE.CylinderGeometry(1.55, 1.55, 8.2, 32, 1, true, Math.PI * 0.55, Math.PI * 0.9),
  mat(0xcfd6dc, { side: THREE.DoubleSide })
);
sBackWall.position.y = 4.6;
const sWater = new THREE.Mesh(new THREE.CylinderGeometry(1.45, 1.45, 6.2, 32), new THREE.MeshStandardMaterial({ color: 0x62beee, transparent: true, opacity: 0.68 }));
sWater.position.y = 3.6;
const sTopCap = new THREE.Mesh(new THREE.CylinderGeometry(1.65, 1.65, 0.32, 32), mat(0xdce2e8));
sTopCap.position.y = 8.75;
secTankGroup.add(sBackWall, sWater, sTopCap);

const hotBridge = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 3.2, 16), mat(0xef6c35));
hotBridge.rotation.z = Math.PI / 2;
hotBridge.position.set(-2.3, 4.2, 0.4);
const coldBridge = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 3.2, 16), mat(0x4ba3e3));
coldBridge.rotation.z = Math.PI / 2;
coldBridge.position.set(-2.3, 1.8, 0.4);
const pumpBody = new THREE.Mesh(new THREE.CylinderGeometry(0.48, 0.48, 0.35, 20), mat(0x3a424a));
pumpBody.rotation.x = Math.PI / 2;
pumpBody.position.set(-2.3, 1.8, 0.55);
secTankGroup.add(hotBridge, coldBridge, pumpBody);

for (let r of [0.55, 0.95]) {
  const uCurve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-r, 1.2, 0),
    new THREE.Vector3(-r, 4.2, 0),
    new THREE.Vector3(0, 4.9, 0),
    new THREE.Vector3(r, 4.2, 0),
    new THREE.Vector3(r, 1.2, 0)
  ]);
  const uTube = new THREE.Mesh(new THREE.TubeGeometry(uCurve, 32, 0.09, 12, false), mat(0xe67838));
  secTankGroup.add(uTube);
}

// 4. 3D Steam Pipe, 3D Spinning Turbine, 3D Green Generator & Streetlamp
const powerGroup = new THREE.Group();
powerGroup.position.set(7.5, 0.3, 1.5);
scene.add(powerGroup);

const turbBase = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.8, 2.2), mat(0xa8aeb5));
turbBase.position.set(-1.2, 0.4, 0);
const turbShell = new THREE.Mesh(
  new THREE.CylinderGeometry(1.15, 1.15, 3.0, 24, 1, false, 0, Math.PI),
  mat(0xc8d0d8, { side: THREE.DoubleSide, metalness: 0.3 })
);
turbShell.rotation.z = Math.PI / 2;
turbShell.rotation.x = -Math.PI / 2;
turbShell.position.set(-1.2, 1.5, 0);
powerGroup.add(turbBase, turbShell);

const rotorGroup = new THREE.Group();
rotorGroup.position.set(-1.2, 1.5, 0);
const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 3.6, 16), mat(0x555c65, { metalness: 0.6 }));
shaft.rotation.z = Math.PI / 2;
rotorGroup.add(shaft);
for (let ring = -1.1; ring <= 1.1; ring += 0.55) {
  for (let b = 0; b < 8; b++) {
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.88, 0.32), mat(0xf4f7fa, { metalness: 0.2 }));
    const ang = (b / 8) * Math.PI * 2 + ring * 0.4;
    blade.position.set(ring, Math.cos(ang) * 0.52, Math.sin(ang) * 0.52);
    blade.rotation.x = ang;
    blade.rotation.y = 0.35;
    rotorGroup.add(blade);
  }
}
powerGroup.add(rotorGroup);

const genMesh = new THREE.Mesh(new THREE.BoxGeometry(2.5, 2.8, 2.2), mat(0x46b48c));
genMesh.position.set(2.0, 1.4, 0);
powerGroup.add(genMesh);

const lampGroup = new THREE.Group();
lampGroup.position.set(4.5, 0, 1.4);
const lampPole = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, 3.8, 12), mat(0x50555a));
lampPole.position.y = 1.9;
const lampBulb = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 16), mat(0xfff275, { emissive: 0xffe040, emissiveIntensity: 0.8 }));
lampBulb.position.y = 3.9;
lampGroup.add(lampPole, lampBulb);
powerGroup.add(lampGroup);

function makeSteamPipe(startX) {
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(startX, 9.1, 1.0),
    new THREE.Vector3(startX, 10.6, 1.0),
    new THREE.Vector3(6.3, 10.6, 1.5),
    new THREE.Vector3(6.3, 2.6, 1.5)
  ]);
  return new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.34, 16, false), mat(0xd8dfe6));
}
const steamPipe1 = makeSteamPipe(-2.5);
const steamPipe2 = makeSteamPipe(2.5);
scene.add(steamPipe1, steamPipe2);

// 5. Condenser & 3D Cooling Tower
const condBox = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.8, 2.0), mat(0x8cbde0));
condBox.position.set(6.3, 1.2, -1.8);
const riverPipeBlue = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 11, 12), mat(0x4aa3e8));
riverPipeBlue.rotation.x = Math.PI / 2;
riverPipeBlue.position.set(6.0, 0.5, -7.5);
const riverPipeRed = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 11, 12), mat(0xeb6434));
riverPipeRed.rotation.x = Math.PI / 2;
riverPipeRed.position.set(6.6, 0.5, -7.5);
scene.add(condBox, riverPipeBlue, riverPipeRed);

const towerGroup = new THREE.Group();
towerGroup.position.set(13.2, 0.3, -2.5);
const towerPts = [];
for (let i = 0; i <= 20; i++) {
  const t = i / 20;
  const y = t * 9.5;
  const r = 3.2 - 1.35 * Math.sin(t * Math.PI * 0.78);
  towerPts.push(new THREE.Vector2(r, y));
}
const towerMat = mat(0xd8d2c4, { side: THREE.DoubleSide, transparent: true, opacity: 1.0 });
const towerMesh = new THREE.Mesh(new THREE.LatheGeometry(towerPts, 32), towerMat);
towerMesh.position.y = 0.8;
const towerBasin = new THREE.Mesh(new THREE.CylinderGeometry(3.5, 3.6, 0.8, 32), mat(0x7cb8de));
towerBasin.position.y = 0.4;
towerGroup.add(towerMesh, towerBasin);

const steamPuffs = [];
for (let i = 0; i < 6; i++) {
  const puff = new THREE.Mesh(new THREE.SphereGeometry(1.2 + i * 0.25, 16, 16), mat(0xffffff, { transparent: true, opacity: 0.78 }));
  puff.userData = { seed: i / 6 };
  towerGroup.add(puff);
  steamPuffs.push(puff);
}
scene.add(towerGroup);

// 6. 3D Steel & Concrete Containment Dome
const domeGroup = new THREE.Group();
domeGroup.position.set(0.0, 0.3, 1.0);
const domeCyl = new THREE.Mesh(
  new THREE.CylinderGeometry(5.6, 5.6, 7.5, 32, 1, true, Math.PI * 0.5, Math.PI),
  mat(0x90969c, { side: THREE.DoubleSide })
);
domeCyl.position.y = 3.75;
const domeCap = new THREE.Mesh(
  new THREE.SphereGeometry(5.6, 32, 20, Math.PI * 0.5, Math.PI, 0, Math.PI * 0.5),
  mat(0x90969c, { side: THREE.DoubleSide })
);
domeCap.position.y = 7.5;
const archPts = [];
for (let a = 0; a <= 32; a++) {
  const ang = (a / 32) * Math.PI;
  archPts.push(new THREE.Vector3(Math.cos(ang) * 5.6, 7.5 + Math.sin(ang) * 5.6, 0));
}
const archCurve = new THREE.CatmullRomCurve3([
  new THREE.Vector3(-5.6, 0, 0),
  new THREE.Vector3(-5.6, 7.5, 0),
  ...archPts.slice().reverse(),
  new THREE.Vector3(5.6, 7.5, 0),
  new THREE.Vector3(5.6, 0, 0)
]);
const archWall = new THREE.Mesh(new THREE.TubeGeometry(archCurve, 64, 0.58, 12, false), mat(0xcfd3d7));
domeGroup.add(domeCyl, domeCap, archWall);
scene.add(domeGroup);

// 7. 3D Backup Diesel Generators & Gravity Water Tank
const backupGroup = new THREE.Group();
backupGroup.position.set(-8.2, 0.3, 1.0);
const diesel1 = new THREE.Mesh(new THREE.BoxGeometry(2.2, 2.2, 1.8), mat(0xebc034));
diesel1.position.set(0, 1.1, 0);
const diesel2 = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.7, 1.6), mat(0xdfb228));
diesel2.position.set(1.6, 0.85, 0);
const gravTank = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 1.6, 2.4, 24), mat(0x7cb8de));
gravTank.position.set(0.8, 7.8, -0.5);
for (let lx of [-0.3, 1.9]) {
  for (let lz of [-1.4, 0.4]) {
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 6.8, 8), mat(0x606870));
    leg.position.set(lx, 3.4, lz);
    backupGroup.add(leg);
  }
}
const gravPipe = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 5.5, 12), mat(0x4ba3e3));
gravPipe.rotation.z = Math.PI / 2;
gravPipe.position.set(3.5, 7.2, 0);
backupGroup.add(diesel1, diesel2, gravTank, gravPipe);
scene.add(backupGroup);

// 8. 3D Spent Fuel Pool
const poolGroup = new THREE.Group();
poolGroup.position.set(-12.5, 0.3, 2.2);
const poolWalls = new THREE.Mesh(new THREE.BoxGeometry(3.8, 2.6, 3.4), mat(0xe2e6ea));
poolWalls.position.y = 1.3;
const poolWater = new THREE.Mesh(new THREE.BoxGeometry(3.3, 2.2, 2.9), mat(0x4ab2f0, { transparent: true, opacity: 0.82, emissive: 0x0088ff, emissiveIntensity: 0.45 }));
poolWater.position.y = 1.45;
poolGroup.add(poolWalls, poolWater);
scene.add(poolGroup);

const CAM_KEYFRAMES = [
  { pos0: [-2.5, 8.5, 19.5], look0: [-2.5, 4.8, 0], pos1: [-2.5, 7.2, 16.0], look1: [-2.5, 4.5, 0] },
  { pos0: [-2.5, 7.2, 16.0], look0: [-2.5, 4.5, 0], pos1: [3.2, 8.2, 22.5],  look1: [3.2, 4.2, 0] },
  { pos0: [3.2, 8.2, 22.5],  look0: [3.2, 4.2, 0],  pos1: [-2.5, 6.8, 15.0], look1: [-2.5, 4.2, 0] },
  { pos0: [-2.5, 6.8, 15.0], look0: [-2.5, 4.2, 0], pos1: [-2.5, 7.8, 16.5], look1: [-2.5, 5.2, 0] },
  { pos0: [-2.5, 7.8, 16.5], look0: [-2.5, 5.2, 0], pos1: [0.2, 7.5, 19.5],  look1: [0.2, 4.5, 0] },
  { pos0: [0.2, 7.5, 19.5],  look0: [0.2, 4.5, 0],  pos1: [6.8, 8.5, 18.5],  look1: [6.8, 2.5, -8] },
  { pos0: [6.8, 8.5, 18.5],  look0: [6.8, 2.5, -8], pos1: [11.5, 8.2, 19.5], look1: [12.0, 5.5, -2] },
  { pos0: [11.5, 8.2, 19.5], look0: [12.0, 5.5, -2], pos1: [1.5, 8.8, 25.5], look1: [1.5, 5.0, 0] },
  { pos0: [1.5, 8.8, 25.5],  look0: [1.5, 5.0, 0],  pos1: [-3.2, 8.2, 23.5], look1: [-3.2, 4.5, 0] },
  { pos0: [-3.2, 8.2, 23.5], look0: [-3.2, 4.5, 0], pos1: [-11.5, 7.5, 15.5], look1: [-12.2, 2.2, 2] },
  { pos0: [-11.5, 7.5, 15.5], look0: [-12.2, 2.2, 2], pos1: [-11.5, 7.5, 16.5], look1: [-12.2, 1.5, 2] },
  { pos0: [-11.5, 7.5, 16.5], look0: [-12.2, 1.5, 2], pos1: [1.0, 10.5, 34.0], look1: [1.0, 4.5, 0] }
];

function smoothstep(x) {
  x = Math.max(0, Math.min(1, x));
  return x * x * (3 - 2 * x);
}
function lerp(a, b, t) { return a + (b - a) * t; }

function worldToScreen(x, y, z) {
  const v = new THREE.Vector3(x, y, z);
  v.project(camera);
  return {
    x: (v.x * 0.5 + 0.5) * W,
    y: (-v.y * 0.5 + 0.5) * H
  };
}

function drawSafeCallout(target3D, offsetX, offsetY, text, bgColor) {
  const p = worldToScreen(target3D[0], target3D[1], target3D[2]);
  ctx.font = '800 28px Montserrat, sans-serif';
  const tw = ctx.measureText(text).width;
  const padX = 24, padY = 18;
  const bw = tw + padX * 2, bh = 54;

  const bx = Math.max(bw / 2 + 24, Math.min(W - bw / 2 - 24, p.x + offsetX));
  const by = Math.max(bh / 2 + 120, Math.min(H - bh / 2 - 120, p.y + offsetY));

  ctx.strokeStyle = '#222c35';
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(p.x, p.y);
  ctx.lineTo(bx, by);
  ctx.stroke();

  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = bgColor;
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 3.5;
  ctx.beginPath();
  ctx.roundRect(bx - bw / 2, by - bh / 2, bw, bh, 26);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, bx, by + 1);
}

function drawTempGauge(tempC, label) {
  const gx = 260, gy = 1490, gw = 560, gh = 195;
  ctx.fillStyle = '#f8f5ec';
  ctx.strokeStyle = '#2c353d';
  ctx.lineWidth = 5;
  ctx.beginPath();
  ctx.roundRect(gx, gy, gw, gh, 28);
  ctx.fill();
  ctx.stroke();

  const bx = gx + 36, by = gy + 36, bw = 270, bh = 48;
  ctx.fillStyle = '#e5e5e5';
  ctx.lineWidth = 3.5;
  ctx.beginPath();
  ctx.roundRect(bx, by, bw, bh, 24);
  ctx.fill();
  ctx.stroke();

  const ratio = Math.max(0.08, Math.min(1.0, (tempC - 150) / 1050));
  const isHot = tempC >= 700;
  ctx.fillStyle = isHot ? '#e5392d' : '#2eb85c';
  ctx.beginPath();
  ctx.roundRect(bx + 4, by + 4, (bw - 8) * ratio, bh - 8, 20);
  ctx.fill();

  ctx.font = '900 50px Montserrat, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(Math.round(tempC) + '°C', bx + bw + 22, by + bh / 2 + 2);

  ctx.fillStyle = '#2c353d';
  ctx.font = '800 28px Montserrat, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(label, gx + gw / 2, gy + 140);
}

window.renderSingleFrameB64 = function(segIdx, segProg, globalTime, currentWord) {
  const kf = CAM_KEYFRAMES[segIdx];
  const ep = smoothstep(segProg);
  camera.position.set(
    lerp(kf.pos0[0], kf.pos1[0], ep),
    lerp(kf.pos0[1], kf.pos1[1], ep),
    lerp(kf.pos0[2], kf.pos1[2], ep)
  );
  camera.lookAt(
    lerp(kf.look0[0], kf.look1[0], ep),
    lerp(kf.look0[1], kf.look1[1], ep),
    lerp(kf.look0[2], kf.look1[2], ep)
  );

  clouds3D.forEach(c => {
    c.mesh.position.x = ((c.baseX + globalTime * c.speed + 24) % 48) - 24;
  });

  craneGroup.visible = (segIdx <= 1);
  const rodDrop = (segIdx === 0) ? smoothstep(segProg * 2.2) : 1.0;
  fuelGroup.position.y = lerp(7.2, 2.3, rodDrop);

  const isHot = (segIdx === 0 && segProg > 0.45) || (segIdx >= 1 && segIdx <= 8);
  coreGlowLight.intensity = isHot ? (segIdx === 2 || segIdx === 8 ? 2.6 : 1.5) : 0;
  fuelRods.forEach(r => r.material.color.setHex(isHot ? 0xf29d38 : 0x885c42));

  ctrlGroup.visible = (segIdx >= 2);
  magGroup.visible = (segIdx >= 3);
  if (segIdx === 2) {
    ctrlGroup.position.y = lerp(6.8, 3.2, smoothstep((segProg - 0.35) * 1.8));
  } else if (segIdx === 3) {
    ctrlGroup.position.y = (segProg > 0.58) ? 2.5 : 5.4;
  } else {
    ctrlGroup.position.y = 4.2;
  }

  waterMat1.color.setHex(segIdx >= 4 ? 0x62c4b2 : 0x5ab9ea);
  secTankGroup.visible = (segIdx >= 4);
  powerGroup.visible = (segIdx >= 1);
  steamPipe1.visible = (segIdx >= 1 && segIdx < 4);
  steamPipe2.visible = (segIdx >= 4);

  rotorGroup.rotation.x = globalTime * 14.0;
  boatGroup.position.x = 16 - ((globalTime * 1.8) % 32);

  plumeGroup.visible = (segIdx === 5 || segIdx === 6);
  if (segIdx === 5) {
    fishList.forEach(f => {
      f.group.position.x = f.baseX - segProg * 2.2;
      const col = segProg > 0.38 ? 0xe6958a : 0xa8b8c0;
      f.body.material.color.setHex(col);
      f.tail.material.color.setHex(col);
    });
  }

  condBox.visible = riverPipeBlue.visible = riverPipeRed.visible = (segIdx >= 5);
  towerGroup.visible = (segIdx >= 6);
  towerMat.opacity = (segIdx === 6) ? 0.55 : 0.96;
  steamPuffs.forEach(p => {
    const pr = (p.userData.seed + globalTime * 0.35) % 1.0;
    p.position.set(Math.sin(pr * 5) * 0.4, 9.8 + pr * 4.5, 0);
    const sc = 0.7 + pr * 0.9;
    p.scale.set(sc, sc, sc);
  });

  domeGroup.visible = (segIdx >= 7);
  if (segIdx === 7) {
    domeGroup.position.y = lerp(12.0, 0.3, smoothstep(segProg * 1.6));
  } else {
    domeGroup.position.y = 0.3;
  }

  backupGroup.visible = (segIdx >= 8);
  poolGroup.visible = (segIdx >= 9);

  const showBubbles = (segIdx === 0 && segProg > 0.45) || segIdx >= 1;
  bubbles3D.forEach(b => {
    b.visible = showBubbles;
    const bp = (b.userData.seed + globalTime * b.userData.speed) % 1.0;
    b.position.set(b.userData.x, lerp(1.5, 6.8, bp), b.userData.z);
  });

  renderer.render(scene, camera);

  ctx.clearRect(0, 0, W, H);

  if (segIdx === 0) {
    drawSafeCallout([-2.5, 2.5, 1.0], 230, -70, 'URANIUM FUEL', '#d9822b');
    drawSafeCallout([-4.0, 2.0, 1.0], -190, 90, 'WATER TANK', '#5b9bd5');
  } else if (segIdx === 1) {
    drawSafeCallout([-2.5, 8.8, 1.0], -190, -40, 'STEAM', '#7f9eb2');
    drawSafeCallout([6.3, 2.0, 1.5], -120, -130, 'TURBINE', '#7a8b99');
    drawSafeCallout([9.5, 2.8, 1.5], 0, -140, 'GENERATOR', '#3ea680');
  } else if (segIdx === 2) {
    const tVal = segProg < 0.48 ? lerp(468, 1200, segProg / 0.48) : lerp(1200, 300, (segProg - 0.48) / 0.52);
    drawTempGauge(tVal, 'CORE TEMPERATURE');
    if (segProg > 0.42) {
      drawSafeCallout([-2.0, 4.8, 1.0], 230, -40, 'CONTROL RODS', '#45505b');
    }
  } else if (segIdx === 3) {
    drawSafeCallout([-2.0, 7.8, 1.0], 230, -30, 'ELECTROMAGNETS', '#d63629');
  } else if (segIdx === 4) {
    drawSafeCallout([0.0, 3.0, 1.4], 0, 190, 'CLOSED LOOP', '#d9822b');
    drawSafeCallout([2.5, 4.5, 1.0], 200, -110, 'SECONDARY LOOP', '#4b9cd3');
  } else if (segIdx === 5) {
    drawSafeCallout([6.3, 1.8, -1.8], -160, -90, 'STEAM -> WATER', '#4b9cd3');
    if (segProg > 0.42) {
      drawTempGauge(70, 'RIVER WATER TEMP');
    }
  } else if (segIdx === 6) {
    drawSafeCallout([13.2, 5.2, -2.5], -220, -30, 'COOLING TOWER', '#8a8478');
    drawSafeCallout([13.2, 11.5, -2.5], -160, -40, 'PURE H2O VAPOR', '#4b9cd3');
  } else if (segIdx === 7) {
    drawSafeCallout([0.0, 11.5, 1.0], 0, -90, 'CONTAINMENT DOME (+1m)', '#6d747a');
  } else if (segIdx === 8) {
    drawTempGauge(lerp(745, 1064, Math.min(segProg * 1.5, 1.0)), 'CORE TEMPERATURE');
    drawSafeCallout([-8.2, 1.8, 1.0], -120, -130, 'BACKUP GENERATORS', '#d4a024');
    drawSafeCallout([-7.4, 8.2, 0.5], -80, -110, 'GRAVITY WATER TANK', '#4b9cd3');
  } else if (segIdx === 9) {
    drawSafeCallout([-12.5, 1.8, 2.2], 140, -140, 'SPENT FUEL POOL', '#3992d6');
  } else if (segIdx === 10) {
    ctx.fillStyle = '#faf6eb';
    ctx.strokeStyle = '#2c353d';
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.roundRect(120, 1140, 840, 480, 32);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#7c8690';
    ctx.beginPath();
    ctx.roundRect(235, 1300, 68, 92, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#eb4236';
    ctx.beginPath();
    ctx.arc(375, 1320, 28, 0, Math.PI * 2);
    ctx.roundRect(343, 1335, 64, 58, 18);
    ctx.fill();

    ctx.fillStyle = '#2c353d';
    ctx.font = '800 32px Montserrat, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('1 FUEL PELLET', 315, 1455);

    ctx.fillStyle = '#eba428';
    ctx.font = '900 72px Montserrat, sans-serif';
    ctx.fillText('=', 530, 1355);

    ctx.fillStyle = '#383d42';
    [[690, 1375], [750, 1375], [810, 1375], [720, 1325], [780, 1325], [750, 1275]].forEach(([cx, cy]) => {
      ctx.beginPath();
      ctx.arc(cx, cy, 32, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    ctx.fillStyle = '#2c353d';
    ctx.font = '800 32px Montserrat, sans-serif';
    ctx.fillText('1 TON OF COAL', 750, 1455);
  } else if (segIdx === 11) {
    const colors = ['#ff5252', '#38b6ff', '#ffd628', '#4ce678', '#c864ff'];
    for (let i = 0; i < 85; i++) {
      const cx = (i * 137.5) % W + Math.sin(globalTime * 5 + i) * 20;
      const cy = ((i * 93) + segProg * 1100) % H;
      ctx.fillStyle = colors[i % colors.length];
      ctx.fillRect(cx, cy, 12, 20);
    }
  }

  if (currentWord) {
    const text = currentWord.toUpperCase();
    ctx.font = '900 78px Montserrat, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#222c35';
    ctx.lineWidth = 14;
    ctx.strokeText(text, W / 2, 370);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(text, W / 2, 370);
  }

  finalCtx.drawImage(webglCanvas, 0, 0);
  finalCtx.drawImage(hudCanvas, 0, 0);
  return finalCanvas.toDataURL('image/jpeg', 0.92).split(',')[1];
};

window.renderBatchB64 = function(batchParams) {
  return batchParams.map(p => window.renderSingleFrameB64(p[0], p[1], p[2], p[3]));
};
</script>
</body>
</html>
"""


def render_threejs_video(seg_durations, master_audio, out_video):
    ensure_playwright_chromium()
    from playwright.sync_api import sync_playwright

    html_path = Path("scene_3d.html").resolve()
    html_path.write_text(THREEJS_HTML_TEMPLATE, encoding="utf-8")

    fps = 30
    ffmpeg_proc = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-r", str(fps),
        "-i", "-",
        "-i", master_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "16",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-shortest", out_video
    ], stdin=subprocess.PIPE)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
                "--disable-gpu-sandbox"
            ]
        )
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(f"file://{html_path}", wait_until="networkidle")
        page.wait_for_timeout(600)

        all_frame_tasks = []
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
                all_frame_tasks.append([seg_idx, prog, round(global_t, 4), curr_word])
                global_t += dt

        batch_size = 12
        for b_start in range(0, len(all_frame_tasks), batch_size):
            batch = all_frame_tasks[b_start:b_start + batch_size]
            b64_list = page.evaluate("batch => window.renderBatchB64(batch)", batch)
            for b64_str in b64_list:
                ffmpeg_proc.stdin.write(base64.b64decode(b64_str))

        browser.close()

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()


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

    print("🎙️ Step 1: Generating 100% Consistent English Voiceover & SFX...", flush=True)
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

    print("🎬 Step 2: Rendering True 3D Three.js WebGL Animation Stream...", flush=True)
    raw_video = "raw_3d.mp4"
    render_threejs_video(seg_durations, master_audio, raw_video)

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
