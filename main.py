import os
import json
import time
import urllib.parse
import subprocess
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKENS = [t.strip() for t in os.getenv("YT_REFRESH_TOKENS", "").split(",") if t.strip()]

FB_PAGE_IDS = [p.strip() for p in os.getenv("FB_PAGE_IDS", "").split(",") if p.strip()]
IG_USER_IDS = [i.strip() for i in os.getenv("IG_USER_IDS", "").split(",") if i.strip()]
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()

GRAPH_API = "https://graph.facebook.com/v21.0"


def generate_story():
    prompt = """
    اكتب قصة قصيرة مشوقة وغامضة جداً تصلح لفيديو شورتس وريلز (مدتها حوالي 35-40 ثانية).
    أخرج النتيجة بصيغة JSON فقط بهذا الهيكل:
    {
      "title": "عنوان مشوق جداً للفيديو",
      "scenes": [
        {
          "narration": "النص العربي للمشهد بالتشكيل الصحيح والواضح",
          "image_prompt": "Detailed cinematic vertical 9:16 illustration, dark mysterious atmosphere, 8k, masterpiece"
        }
      ]
    }
    اجعل القصة مقسمة إلى 5 مشاهد مترابطة ومتتالية.
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    for model in ["gemini-4.0-argon", "gemini-2.5-pro", "gemini-2.5-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        res = requests.post(url, json=payload, timeout=60).json()
        if "candidates" in res:
            print(f"تم توليد القصة باستخدام: {model}")
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    raise RuntimeError(f"فشل الاتصال بـ Gemini API: {res}")


def create_scene_assets(index, narration, image_prompt):
    audio_file = f"scene_{index}.mp3"
    subprocess.run([
        "edge-tts", "--voice", "ar-EG-ShakirNeural", "--rate", "+5%",
        "--text", narration, "--write-media", audio_file
    ], check=True)

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())

    encoded_prompt = urllib.parse.quote(image_prompt)
    img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&model=flux&nologo=true&seed={int(time.time()) + index}"
    img_file = f"scene_{index}.jpg"
    img_data = requests.get(img_url, timeout=90).content
    with open(img_file, "wb") as f:
        f.write(img_data)

    video_file = f"scene_{index}.mp4"
    fps = 30
    total_frames = int(duration * fps) + 15
    zoom_filter = (
        f"scale=1280:2276,"
        f"zoompan=z='min(zoom+0.0012,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps}"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", img_file, "-i", audio_file,
        "-vf", zoom_filter, "-c:v", "libx264", "-preset", "ultrafast",
        "-t", str(duration), "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", video_file
    ], check=True)
    return video_file


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
            "description": f"{title}\n\n#قصص #حكايات #غموض #shorts",
            "tags": ["shorts", "قصص", "حكايات", "غموض"],
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"[YouTube] تم الرفع بنجاح: https://youtu.be/{res['id']}")


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
        headers = {
            "Authorization": f"OAuth {META_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        requests.post(upload_url, headers=headers, data=f, timeout=180).raise_for_status()

    finish_res = requests.post(
        f"{GRAPH_API}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": f"{title}\n\n#قصص #حكايات #غموض #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=60
    ).json()
    print(f"[Facebook Reels] تم النشر بنجاح: {finish_res}")


def upload_to_instagram_reels(video_path, title, ig_user_id):
    file_size = os.path.getsize(video_path)
    init_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": f"{title}\n\n#قصص #حكايات #غموض #reels",
            "access_token": META_ACCESS_TOKEN
        },
        timeout=30
    ).json()

    container_id = init_res["id"]
    upload_uri = init_res["uri"]

    with open(video_path, "rb") as f:
        headers = {
            "Authorization": f"OAuth {META_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        requests.post(upload_uri, headers=headers, data=f, timeout=180).raise_for_status()

    for _ in range(20):
        status_res = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code", "access_token": META_ACCESS_TOKEN},
            timeout=30
        ).json()
        if status_res.get("status_code") == "FINISHED":
            break
        time.sleep(5)

    pub_res = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": META_ACCESS_TOKEN},
        timeout=60
    ).json()
    print(f"[Instagram Reels] تم النشر بنجاح: {pub_res}")


def assemble_and_publish():
    print("جاري كتابة القصة عبر Gemini...")
    story = generate_story()
    print(f"عنوان القصة: {story['title']}")

    scene_videos = []
    for idx, scene in enumerate(story["scenes"]):
        print(f"جاري تجهيز المشهد {idx + 1}...")
        clip = create_scene_assets(idx, scene["narration"], scene["image_prompt"])
        scene_videos.append(clip)

    with open("inputs.txt", "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final_video = "final_short.mp4"
    print("جاري دمج الفيديو النهائي...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "inputs.txt", "-c", "copy", final_video
    ], check=True)

    for token in YT_REFRESH_TOKENS:
        try:
            upload_to_youtube(final_video, story["title"], token)
        except Exception as e:
            print(f"[YouTube Error] {e}")

    if META_ACCESS_TOKEN:
        for page_id in FB_PAGE_IDS:
            try:
                upload_to_facebook_reels(final_video, story["title"], page_id)
            except Exception as e:
                print(f"[Facebook Error] {e}")

        for ig_id in IG_USER_IDS:
            try:
                upload_to_instagram_reels(final_video, story["title"], ig_id)
            except Exception as e:
                print(f"[Instagram Error] {e}")


if __name__ == "__main__":
    assemble_and_publish()
