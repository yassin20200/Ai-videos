import os
import json
import time
import urllib.parse
import subprocess
import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def generate_story():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = """
    اكتب قصة قصيرة مشوقة وغامضة تصلح لفيديو يوتيوب شورتس (مدتها 40 ثانية).
    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان جذاب للفيديو مع هاشتاجات",
      "scenes": [
        {
          "narration": "النص العربي الذي سيقرأه المعلق في هذا المشهد بالتشكيل الصحيح",
          "image_prompt": "Detailed cinematic vertical 9:16 illustration of the scene, dark dramatic lighting, 8k, masterpiece"
        }
      ]
    }
    اجعل القصة مكونة من 5 مشاهد مترابطة.
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    res = requests.post(url, json=payload).json()
    text = res["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)

def create_scene_assets(index, narration, image_prompt):
    # 1. توليد الصوت بـ Edge-TTS
    audio_file = f"scene_{index}.mp3"
    subprocess.run([
        "edge-tts",
        "--voice", "ar-EG-ShakirNeural",
        "--rate", "+5%",
        "--text", narration,
        "--write-media", audio_file
    ], check=True)

    # 2. حساب مدة الصوت بالثواني
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())

    # 3. تحميل الصورة من Pollinations (Flux)
    encoded_prompt = urllib.parse.quote(image_prompt)
    img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&model=flux&nologo=true&seed={int(time.time()) + index}"
    img_file = f"scene_{index}.jpg"
    img_data = requests.get(img_url, timeout=60).content
    with open(img_file, "wb") as f:
        f.write(img_data)

    # 4. عمل مونتاج للمشهد مع تأثير Zoom سينمائي
    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15
    zoom_filter = (
        f"scale=2160:3840,"
        f"zoompan=z='min(zoom+0.0012,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps}"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", img_file,
        "-i", audio_file,
        "-vf", zoom_filter,
        "-c:v", "libx264", "-t", str(duration),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        video_file
    ], check=True)
    return video_file

def assemble_and_publish():
    story = generate_story()
    scene_videos = []

    for idx, scene in enumerate(story["scenes"]):
        clip = create_scene_assets(idx, scene["narration"], scene["image_prompt"])
        scene_videos.append(clip)

    # دمج المشاهد في فيديو نهائي واحد
    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final_video = "final_short.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", final_video
    ], check=True)

    # إرسال الفيديو النهائي إلى تيليجرام (أو ربطه بـ API المنصات)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        with open(final_video, "rb") as video:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": story["title"]},
                files={"video": video}
            )

if __name__ == "__main__":
    assemble_and_publish()
