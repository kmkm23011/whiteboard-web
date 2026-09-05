import os, subprocess, tempfile, asyncio, shutil, uuid
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import edge_tts

FPS = 24
OUT_DIR = "/tmp/wb_out"
os.makedirs(OUT_DIR, exist_ok=True)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

VOICES = {
    "Bengali - Nabanita (female)": "bn-BD-NabanitaNeural",
    "Bengali - Pradeep (male)": "bn-BD-PradeepNeural",
    "Bengali India - Tanishaa (female)": "bn-IN-TanishaaNeural",
    "Hindi - Swara (female)": "hi-IN-SwaraNeural",
    "English - Aria (female)": "en-US-AriaNeural",
    "English - Guy (male)": "en-US-GuyNeural",
    "No voice (silent)": "",
}

SIZES = {"720p (fast)": (1280, 720), "1080p (best)": (1920, 1080)}


def find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    for root, _, files in os.walk("/usr/share/fonts"):
        for f in sorted(files):
            if f.lower().endswith((".ttf", ".otf")):
                return os.path.join(root, f)
    return None


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


async def _tts(text, voice, path):
    await edge_tts.Communicate(text, voice).save(path)


def make_voice(text, voice, path):
    asyncio.run(_tts(text, voice, path))


def media_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        return float(subprocess.check_output(cmd).decode().strip())
    except Exception:
        return 0.0


def wrap_lines(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_pen(dr, tip, h):
    x, y = tip
    length = h * 0.20
    dx, dy = length * 0.55, length * 0.95
    bw = max(3, int(h * 0.022))
    dr.line([(x + dx * 0.12, y + dy * 0.12), (x + dx, y + dy)],
            fill=(40, 40, 40), width=bw)
    dr.line([(x, y), (x + dx * 0.18, y + dy * 0.18)],
            fill=(95, 95, 95), width=max(2, int(bw * 0.45)))
    g = int(h * 0.05)
    cx, cy = x + dx * 0.55, y + dy * 0.55
    dr.ellipse([cx - g, cy - g, cx + g, cy + g],
               fill=(242, 205, 176), outline=(190, 150, 120), width=2)


def draw_dots(dr, w, h):
    r = max(2, int(h * 0.008))
    cy = int(h * 0.90)
    for i, c in enumerate([(80, 140, 220), (120, 190, 110), (225, 170, 60)]):
        cx = int(w * 0.5) + (i - 1) * int(h * 0.045)
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)


def render_scene(text, w, h, font_path, frames_dir, n_frames, start_index):
    fs = int(h * 0.072)
    font = ImageFont.truetype(font_path, fs)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = wrap_lines(probe, text, font, int(w * 0.80))
    total_chars = sum(len(l) for l in lines) or 1

    line_h = int(fs * 1.55)
    top = max(int(h * 0.12), (h - line_h * len(lines)) // 2)
    idx = start_index

    for i in range(n_frames):
        raw = i / max(1, n_frames - 1)
        prog = min(1.0, raw / 0.85)
        shown = int(round(total_chars * prog))

        img = Image.new("RGB", (w, h), (252, 252, 250))
        dr = ImageDraw.Draw(img)

        remaining, tip, last_box = shown, None, None
        for li, line in enumerate(lines):
            tw = dr.textlength(line, font=font)
            x = (w - tw) / 2
            y = top + li * line_h
            if remaining <= 0:
                break
            part = line[:remaining]
            dr.text((x, y), part, font=font, fill=(35, 35, 40))
            pw = dr.textlength(part, font=font)
            tip = (x + pw, y + fs * 0.85)
            last_box = (x, y, x + tw)
            remaining -= len(line)

        if prog >= 1.0 and last_box:
            x0, y0, x1 = last_box
            uy = y0 + fs * 1.18
            span = (x1 - x0) * 0.35
            dr.line([(x1 - span, uy), (x1, uy)],
                    fill=(235, 160, 70), width=max(3, int(h * 0.006)))

        if tip and prog < 1.0:
            draw_pen(dr, tip, h)

        draw_dots(dr, w, h)
        img.save(os.path.join(frames_dir, f"{idx:06d}.png"))
        idx += 1

    return idx


def build_video(script, voice, size_label, min_sec, bar, note):
    font_path = find_font()
    if not font_path:
        return None, "No font found. Check packages.txt."

    lines = [l.strip() for l in script.split("\n") if l.strip()]
    if not lines:
        return None, "Please write at least one line."
    if len(lines) > 30:
        return None, "Please keep it under 30 lines on the free tier."

    w, h = SIZES[size_label]
    work = tempfile.mkdtemp()
    frames_dir = os.path.join(work, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    total_steps = len(lines) * 2 + 2
    step = 0
    seg_frames, seg_audio = [], []

    for i, line in enumerate(lines):
        note.info(f"Voice {i+1} / {len(lines)}")
        mp3 = os.path.join(work, f"v{i:03d}.mp3")
        spoken = 0.0
        if voice:
            try:
                make_voice(line, voice, mp3)
                spoken = media_duration(mp3)
            except Exception:
                spoken = 0.0
        dur = max(float(min_sec), spoken + 0.45)
        nf = max(1, int(round(dur * FPS)))
        exact = nf / FPS
        seg_frames.append(nf)

        wav = os.path.join(work, f"s{i:03d}.wav")
        if spoken > 0:
            run(["ffmpeg", "-y", "-i", mp3, "-ar", "24000", "-ac", "1",
                 "-af", "apad", "-t", f"{exact:.3f}", wav])
        else:
            run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                 "anullsrc=r=24000:cl=mono", "-t", f"{exact:.3f}", wav])
        seg_audio.append(wav)
        step += 1
        bar.progress(step / total_steps)

    idx = 0
    for i, line in enumerate(lines):
        note.info(f"Drawing {i+1} / {len(lines)}")
        idx = render_scene(line, w, h, font_path, frames_dir,
                           seg_frames[i], idx)
        step += 1
        bar.progress(step / total_steps)

    note.info("Encoding video")
    silent = os.path.join(work, "silent.mp4")
    run(["ffmpeg", "-y", "-framerate", str(FPS),
         "-i", os.path.join(frames_dir, "%06d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", silent])
    step += 1
    bar.progress(step / total_steps)

    note.info("Adding audio")
    listfile = os.path.join(work, "alist.txt")
    with open(listfile, "w") as f:
        for a in seg_audio:
            f.write(f"file '{a}'\n")
    joined = os.path.join(work, "voice.wav")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", joined])

    out_path = os.path.join(OUT_DIR, f"whiteboard_{uuid.uuid4().hex[:8]}.mp4")
    run(["ffmpeg", "-y", "-i", silent, "-i", joined, "-c:v", "copy",
         "-c:a", "aac", "-b:a", "128k", "-shortest", out_path])

    shutil.rmtree(work, ignore_errors=True)
    bar.progress(1.0)
    total = sum(seg_frames) / FPS
    return out_path, f"Done. {len(lines)} scenes, {total:.1f} seconds."


st.set_page_config(page_title="Whiteboard Pro", layout="centered")
st.title("Whiteboard Video Maker")
st.caption("Write one sentence per line.")

script = st.text_area("Script", height=180,
                      placeholder="One sentence per line")
voice_label = st.selectbox("Voice", list(VOICES.keys()))
size_label = st.selectbox("Resolution", list(SIZES.keys()))
min_sec = st.slider("Minimum seconds per line", 1.5, 8.0, 3.0, 0.5)

if st.button("CREATE VIDEO", type="primary", use_container_width=True):
    bar = st.progress(0.0)
    note = st.empty()
    try:
        path, msg = build_video(script, VOICES[voice_label], size_label,
                                min_sec, bar, note)
        note.empty()
        if path:
            st.session_state["last_video"] = path
            st.success(msg)
        else:
            st.error(msg)
    except Exception as e:
        note.empty()
        st.error(f"Failed: {e}")

if st.session_state.get("last_video") and os.path.exists(st.session_state["last_video"]):
    p = st.session_state["last_video"]
    st.video(p)
    with open(p, "rb") as f:
        st.download_button("DOWNLOAD MP4", f, file_name=os.path.basename(p),
                           mime="video/mp4", use_container_width=True)
  
