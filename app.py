import os
import glob
import shutil
import asyncio
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="হোয়াইটবোর্ড ভিডিও মেকার", layout="centered")

FONT_URL = ("https://github.com/google/fonts/raw/main/ofl/"
            "notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf")

VOICES = {
    "বাংলাদেশ - নবনীতা (মহিলা)": "bn-BD-NabanitaNeural",
    "বাংলাদেশ - প্রদীপ (পুরুষ)": "bn-BD-PradeepNeural",
    "ভারত - তানিশা (মহিলা)": "bn-IN-TanishaaNeural",
    "ভারত - ভাস্কর (পুরুষ)": "bn-IN-BashkarNeural",
    "English - Aria (female)": "en-US-AriaNeural",
    "English - Guy (male)": "en-US-GuyNeural",
    "কোনো ভয়েস নয় (নীরব)": None,
}


@st.cache_resource(show_spinner=False)
def get_font_path():
    patterns = ["**/NotoSansBengali*.ttf", "**/NotoSerifBengali*.ttf",
                "**/*Bengali*.ttf", "**/*Beng*.ttf", "**/Lohit-Bengali*.ttf"]
    for base in ("/usr/share/fonts", "/usr/local/share/fonts"):
        for pat in patterns:
            hits = glob.glob(os.path.join(base, pat), recursive=True)
            if hits:
                return hits[0]
    local = Path("NotoSansBengali.ttf")
    if local.exists():
        return str(local)
    try:
        req = urllib.request.Request(FONT_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(local, "wb") as f:
            f.write(r.read())
        return str(local)
    except Exception:
        return None


def load_font(size, uploaded_path=None):
    path = uploaded_path or get_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_voice(text, voice, out_path, rate="+0%"):
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, voice, rate=rate).save(out_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def audio_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True)
        return max(0.4, float(r.stdout.strip()))
    except Exception:
        return None


def _is_mark(ch):
    o = ord(ch)
    return (0x0981 <= o <= 0x0983) or (0x09BC <= o <= 0x09CD) or \
           o in (0x09D7, 0x200C, 0x200D)


def safe_cut(s, n):
    n = max(0, min(n, len(s)))
    while n < len(s) and (_is_mark(s[n]) or (n > 0 and ord(s[n - 1]) == 0x09CD)):
        n += 1
    return n


def wrap_lines(text, font, max_w):
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if not cur or d.textlength(test, font=font) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_base(W, H, title, font_title):
    img = Image.new("RGB", (W, H), (252, 252, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(225, 225, 220), width=max(2, W // 480))
    if title:
        tw = d.textlength(title, font=font_title)
        d.text(((W - tw) / 2, H * 0.055), title, font=font_title, fill=(25, 60, 130))
        d.line([(W * 0.18, H * 0.16), (W * 0.82, H * 0.16)],
               fill=(80, 140, 200), width=max(2, H // 260))
    return img


def draw_pen(d, x, y, s):
    d.line([(x, y), (x + 0.9 * s, y + 1.6 * s)], fill=(35, 35, 40),
           width=max(3, int(s * 0.22)))
    d.line([(x + 0.9 * s, y + 1.6 * s), (x + 1.35 * s, y + 2.4 * s)],
           fill=(150, 110, 60), width=max(3, int(s * 0.26)))
    d.polygon([(x - 0.1 * s, y - 0.15 * s), (x + 0.25 * s, y + 0.05 * s),
               (x + 0.05 * s, y + 0.3 * s)], fill=(15, 15, 15))


def render_frame(base, lines, font, n_chars, x0, y0, line_h, pen_size, show_pen):
    img = base.copy()
    d = ImageDraw.Draw(img)
    left = n_chars
    tip = None
    for i, line in enumerate(lines):
        if left <= 0:
            break
        k = safe_cut(line, min(len(line), left))
        part = line[:k]
        y = y0 + i * line_h
        d.text((x0, y), part, font=font, fill=(25, 25, 30))
        tip = (x0 + d.textlength(part, font=font), y)
        left -= len(line)
    if show_pen and tip:
        draw_pen(d, tip[0] + pen_size * 0.15, tip[1] + line_h * 0.55, pen_size)
    return img


def build_scene(text, idx, cfg, workdir, font, font_title):
    W, H, fps = cfg["W"], cfg["H"], cfg["fps"]
    audio = os.path.join(workdir, f"a{idx}.mp3")
    have_audio = False

    if cfg["voice"]:
        try:
            make_voice(text, cfg["voice"], audio, cfg["rate"])
            have_audio = os.path.exists(audio) and os.path.getsize(audio) > 500
        except Exception as e:
            st.warning(f"দৃশ্য {idx + 1}: ভয়েস তৈরি হয়নি ({e}) — নীরব থাকবে।")

    dur = audio_duration(audio) if have_audio else None
    if not dur:
        dur = max(2.0, len(text) / 11.0)
    dur += cfg["pause"]

    margin = int(W * 0.09)
    lines = wrap_lines(text, font, W - 2 * margin)
    line_h = int(font.size * 1.55)
    block_h = line_h * len(lines)
    y0 = int(H * 0.22) if cfg["title"] else max(int(H * 0.12), (H - block_h) // 2)
    total_chars = sum(len(l) for l in lines) or 1

    base = make_base(W, H, cfg["title"], font_title)
    total_frames = max(int(dur * fps), 6)
    write_frames = max(int(total_frames * 0.82), 1)

    out = os.path.join(workdir, f"s{idx}.mp4")
    logf = os.path.join(workdir, f"s{idx}.log")

    cmd = ["ffmpeg", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-"]
    if have_audio:
        cmd += ["-i", audio]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            "-movflags", "+faststart", out]

    with open(logf, "w") as log:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        last_n, last_img = -1, None
        try:
            for f in range(total_frames):
                prog = min(1.0, f / write_frames)
                n = int(total_chars * prog)
                show_pen = prog < 1.0
                if n != last_n or last_img is None:
                    last_img = render_frame(base, lines, font, n, margin, y0,
                                            line_h, int(font.size * 0.9), show_pen)
                    last_n = n
                last_img.save(p.stdin, format="JPEG", quality=87)
            p.stdin.close()
        except BrokenPipeError:
            pass
        p.wait()

    if p.returncode != 0 or not os.path.exists(out):
        with open(logf) as log:
            st.error("FFmpeg সমস্যা:\n" + log.read()[-1500:])
        return None
    return out


def concat(parts, workdir):
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    final = os.path.join(workdir, "final.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", "-movflags", "+faststart", final],
                       capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
                            "-c:a", "aac", "-movflags", "+faststart", final],
                           capture_output=True, text=True)
    if r.returncode != 0:
        st.error("জোড়া লাগাতে সমস্যা:\n" + r.stderr[-1500:])
        return None
    return final


st.title("হোয়াইটবোর্ড ভিডিও মেকার")
st.caption("বাংলা স্ক্রিপ্ট দিন, ভয়েসসহ ভিডিও তৈরি হবে।")

title = st.text_input("ভিডিওর শিরোনাম (না চাইলে ফাঁকা রাখুন)", "")
script = st.text_area(
    "স্ক্রিপ্ট — প্রতিটি লাইন একটি দৃশ্য",
    "আমার প্রথম হোয়াইটবোর্ড ভিডিও\nএখানে লেখা ধীরে ধীরে ফুটে উঠবে।",
    height=180)

vname = st.selectbox("ভয়েস", list(VOICES.keys()))
speed = st.slider("কথার গতি (%)", -40, 40, 0, 5)
quality = st.radio("রেজোলিউশন", ["720p (দ্রুত)", "1080p (ভালো)"], horizontal=True)
with st.expander("আরও সেটিং"):
    fps = st.select_slider("ফ্রেম রেট", [8, 10, 12, 15], value=10)
    fsize = st.slider("লেখার আকার", 30, 90, 52, 2)
    pause = st.slider("প্রতি দৃশ্যের শেষে বিরতি (সেকেন্ড)", 0.0, 2.0, 0.6, 0.2)
    upfont = st.file_uploader("নিজের ফন্ট দিন (.ttf) — ঐচ্ছিক", type=["ttf", "otf"])

go = st.button("ভিডিও তৈরি করুন", type="primary", use_container_width=True)

if go:
    scenes = [s.strip() for s in script.splitlines() if s.strip()]
    if not scenes:
        st.warning("অন্তত একটি লাইন লিখুন।")
        st.stop()
    if not shutil.which("ffmpeg"):
        st.error("ffmpeg পাওয়া যায়নি। packages.txt ঠিক আছে কি না দেখে অ্যাপ Reboot করুন।")
        st.stop()

    W, H = (1280, 720) if quality.startswith("720") else (1920, 1080)
    scale = H / 1080.0

    workdir = tempfile.mkdtemp(prefix="wb_")
    upath = None
    if upfont is not None:
        upath = os.path.join(workdir, "user.ttf")
        with open(upath, "wb") as f:
            f.write(upfont.read())

    font = load_font(max(14, int(fsize * 1.9 * scale)), upath)
    font_title = load_font(max(16, int(fsize * 2.3 * scale)), upath)
    if isinstance(font, ImageFont.ImageFont):
        st.warning("বাংলা ফন্ট পাওয়া যায়নি, লেখা ভাঙা দেখাতে পারে। "
                   "'আরও সেটিং' থেকে একটি বাংলা .ttf ফন্ট দিন।")

    cfg = dict(W=W, H=H, fps=fps, voice=VOICES[vname],
               rate=f"{speed:+d}%", title=title.strip(), pause=pause)

    bar = st.progress(0.0, text="শুরু হচ্ছে...")
    parts = []
    for i, s in enumerate(scenes):
        bar.progress(i / len(scenes), text=f"দৃশ্য {i + 1}/{len(scenes)} তৈরি হচ্ছে...")
        part = build_scene(s, i, cfg, workdir, font, font_title)
        if part is None:
            st.stop()
        parts.append(part)

    bar.progress(0.97, text="জোড়া লাগানো হচ্ছে...")
    final = parts[0] if len(parts) == 1 else concat(parts, workdir)
    if not final:
        st.stop()
    bar.progress(1.0, text="সম্পন্ন")

    with open(final, "rb") as f:
        st.session_state["video"] = f.read()

if st.session_state.get("video"):
    st.success("ভিডিও তৈরি হয়েছে।")
    st.video(st.session_state["video"])
    st.download_button("ডাউনলোড করুন (MP4)", st.session_state["video"],
                       file_name="whiteboard.mp4", mime="video/mp4",
                       use_container_width=True)

with st.expander("Diagnostics"):
    import sys
    st.write("ffmpeg:", shutil.which("ffmpeg"))
    st.write("ffprobe:", shutil.which("ffprobe"))
    st.write("font:", get_font_path())
    st.write("python:", sys.version.split()[0])
    try:
        import edge_tts
        st.write("edge-tts: OK")
    except Exception as e:
        st.write("edge-tts fail:", e)
        
