import os, io, re, glob, json, shutil, asyncio, subprocess, tempfile, sys
import urllib.parse, urllib.request
from pathlib import Path
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(page_title="হোয়াইটবোর্ড ভিডিও", layout="centered")

FURL = ("https://github.com/google/fonts/raw/main/ofl/notosansbengali/"
        "NotoSansBengali%5Bwdth%2Cwght%5D.ttf")
INK, BG = (32, 32, 40), (252, 252, 250)

VOICES = {
    "বাংলাদেশ - নবনীতা (মহিলা)": "bn-BD-NabanitaNeural",
    "বাংলাদেশ - প্রদীপ (পুরুষ)": "bn-BD-PradeepNeural",
    "ভারত - তানিশা (মহিলা)": "bn-IN-TanishaaNeural",
    "ভারত - ভাস্কর (পুরুষ)": "bn-IN-BashkarNeural",
    "English - Aria": "en-US-AriaNeural",
    "English - Guy": "en-US-GuyNeural",
    "নীরব": None,
}

BN2EN = {
    "গাছ": "tree", "ফুল": "flower", "পাতা": "leaf", "সূর্য": "sun",
    "চাঁদ": "moon", "তারা": "star", "মেঘ": "cloud", "আকাশ": "cloud",
    "বৃষ্টি": "rain", "পানি": "water", "জল": "water", "নদী": "river",
    "সমুদ্র": "sea", "পাহাড়": "mountain", "আগুন": "fire", "বাতাস": "wind",
    "পৃথিবী": "earth", "পাখি": "bird", "মাছ": "fish", "অক্সিজেন": "lungs",
    "মানুষ": "person", "ছেলে": "boy", "মেয়ে": "girl", "শিশু": "child",
    "পরিবার": "family", "মা": "mother", "বাবা": "father", "বন্ধু": "friends",
    "শিক্ষক": "teacher", "ছাত্র": "student", "ডাক্তার": "doctor",
    "কৃষক": "farmer", "বই": "book", "পড়া": "book", "শিক্ষা": "school",
    "স্কুল": "school", "পরীক্ষা": "exam", "কলম": "pen", "খাতা": "notebook",
    "জ্ঞান": "idea", "চিন্তা": "idea", "বুদ্ধি": "brain", "মন": "brain",
    "স্বাস্থ্য": "health", "শরীর": "body", "রোগ": "virus", "ঔষধ": "pill",
    "খাবার": "food", "ভাত": "rice", "ফল": "apple", "সবজি": "carrot",
    "দুধ": "milk", "ঘুম": "sleep", "ব্যায়াম": "run", "টাকা": "money",
    "ব্যবসা": "shop", "কাজ": "work", "চাকরি": "briefcase", "সময়": "clock",
    "ঘড়ি": "clock", "বছর": "calendar", "দিন": "sun", "রাত": "moon",
    "ভবিষ্যৎ": "rocket", "উন্নতি": "growth", "কম্পিউটার": "computer",
    "মোবাইল": "smartphone", "ফোন": "phone", "ইন্টারনেট": "wifi",
    "প্রযুক্তি": "chip", "যন্ত্র": "gear", "বিজ্ঞান": "flask",
    "গবেষণা": "microscope", "শক্তি": "bolt", "ঘর": "home", "বাড়ি": "home",
    "গাড়ি": "car", "রাস্তা": "road", "শহর": "city", "গ্রাম": "village",
    "দেশ": "flag", "পথ": "road", "ভালোবাসা": "heart", "ভালবাসা": "heart",
    "খুশি": "smile", "হাসি": "smile", "দুঃখ": "sad", "ভয়": "warning",
    "সাহায্য": "hand", "সফলতা": "trophy", "লক্ষ্য": "target",
    "প্রশ্ন": "question", "উত্তর": "check", "সমাধান": "key",
    "সমস্যা": "warning", "নিয়ম": "list", "খেলা": "football",
}


@st.cache_resource(show_spinner=False)
def font_path():
    for base in ("/usr/share/fonts", "/usr/local/share/fonts"):
        for p in ("**/NotoSansBengali*.ttf", "**/*Bengali*.ttf", "**/*Beng*.ttf"):
            h = glob.glob(os.path.join(base, p), recursive=True)
            if h:
                return h[0]
    loc = Path("NotoSansBengali.ttf")
    if loc.exists():
        return str(loc)
    try:
        rq = urllib.request.Request(FURL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(rq, timeout=60) as r, open(loc, "wb") as f:
            f.write(r.read())
        return str(loc)
    except Exception:
        return None


def load_font(size, up=None):
    p = up or font_path()
    if p:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_voice(text, voice, out, rate="+0%"):
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate).save(out)

    lp = asyncio.new_event_loop()
    asyncio.set_event_loop(lp)
    try:
        lp.run_until_complete(go())
    finally:
        lp.close()
        asyncio.set_event_loop(None)


def dur_of(p):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "default=nw=1:nk=1", p],
                           capture_output=True, text=True)
        return max(0.5, float(r.stdout.strip()))
    except Exception:
        return None


def _get(url, t=30):
    rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(rq, timeout=t) as r:
        return r.read()


def keyword_of(text):
    for w in re.findall(r"[\u0980-\u09FF]+", text):
        if w in BN2EN:
            return BN2EN[w]
        for c in (1, 2, 3):
            if len(w) > c + 1 and w[:-c] in BN2EN:
                return BN2EN[w[:-c]]
    e = re.findall(r"[A-Za-z]{3,}", text)
    return max(e, key=len).lower() if e else None


@st.cache_data(show_spinner=False, ttl=86400)
def icon_svg(kw):
    try:
        d = json.loads(_get("https://api.iconify.design/search?query="
                            + urllib.parse.quote(kw) + "&limit=10"))
        ic = d.get("icons") or []
        if not ic:
            return None
        good = ("mdi", "ph", "tabler", "lucide", "carbon", "solar", "iconoir")
        pf = [i for i in ic if i.split(":")[0] in good]
        pre, nm = (pf or ic)[0].split(":", 1)
        return _get(f"https://api.iconify.design/{pre}/{nm}.svg?height=600")
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=86400)
def ai_png(kw, seed):
    try:
        pr = ("simple black ink line drawing of " + kw + ", hand drawn "
              "whiteboard doodle, thin clean outlines, plain white "
              "background, no colour, no shading, no text")
        return _get("https://image.pollinations.ai/prompt/"
                    + urllib.parse.quote(pr)
                    + f"?width=640&height=640&nologo=true&seed={seed}", 120)
    except Exception:
        return None


def to_ink(png, box):
    try:
        g = ImageOps.autocontrast(Image.open(io.BytesIO(png)).convert("L"))
        g = g.resize((box, box), Image.LANCZOS)
        a = g.point(lambda v: 255 if v < 190 else 0)
        if a.getbbox() is None:
            return None
        im = Image.new("RGBA", (box, box), INK + (255,))
        im.putalpha(a)
        return im
    except Exception:
        return None


def get_art(kw, mode, box, seed):
    if not kw or mode == "ছবি ছাড়া":
        return None
    if mode != "AI ছবি":
        s = icon_svg(kw)
        if s:
            try:
                import cairosvg
                p = cairosvg.svg2png(bytestring=s, output_width=box,
                                     output_height=box,
                                     background_color="white")
                a = to_ink(p, box)
                if a is not None:
                    return a
            except Exception:
                pass
        if mode == "আইকন":
            return None
    p = ai_png(kw, seed)
    return to_ink(p, box) if p else None


def _mk(c):
    o = ord(c)
    return (0x0981 <= o <= 0x0983) or (0x09BC <= o <= 0x09CD) or \
        o in (0x09D7, 0x200C, 0x200D)


def safe_cut(s, n):
    n = max(0, min(n, len(s)))
    while n < len(s) and (_mk(s[n]) or (n > 0 and ord(s[n - 1]) == 0x09CD)):
        n += 1
    return n


def wrap(text, font, mw):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if not cur or d.textlength(t, font=font) <= mw:
            cur = t
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def base_img(W, H, title, ft):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, H - 1], outline=(224, 224, 218),
                width=max(2, W // 500))
    if title:
        tw = d.textlength(title, font=ft)
        d.text(((W - tw) / 2, H * 0.05), title, font=ft, fill=(25, 60, 130))
        d.line([(W * 0.16, H * 0.155), (W * 0.84, H * 0.155)],
               fill=(80, 140, 200), width=max(2, H // 300))
    return im


def frame(base, art, axy, af, lines, font, nc, tx, ty, lh):
    im = base.copy()
    if art is not None and af > 0:
        w, h = art.size
        cut = max(1, int(w * af))
        pc = art if af >= 1 else art.crop((0, 0, cut, h))
        im.paste(pc, axy, pc)
    if nc > 0:
        d = ImageDraw.Draw(im)
        left = nc
        for i, ln in enumerate(lines):
            if left <= 0:
                break
            k = safe_cut(ln, min(len(ln), left))
            d.text((tx, ty + i * lh), ln[:k], font=font, fill=INK)
            left -= len(ln)
    return im


def scene(raw, idx, cfg, wd, font, ft, box):
    if "|" in raw:
        text, kw = [x.strip() for x in raw.split("|", 1)]
    else:
        text, kw = raw.strip(), keyword_of(raw)

    W, H, fps = cfg["W"], cfg["H"], cfg["fps"]
    au = os.path.join(wd, f"a{idx}.mp3")
    have = False
    if cfg["voice"]:
        try:
            make_voice(text, cfg["voice"], au, cfg["rate"])
            have = os.path.exists(au) and os.path.getsize(au) > 500
        except Exception as e:
            st.warning(f"দৃশ্য {idx+1}: ভয়েস হয়নি ({e})")

    dur = (dur_of(au) if have else None) or max(2.2, len(text) / 11.0)
    dur += cfg["pause"]

    art = get_art(kw, cfg["mode"], box, idx + 3)
    if art is None:
        tx, tw, axy = int(W * 0.09), int(W * 0.82), None
    else:
        tx, tw = int(W * 0.07), int(W * 0.50)
        axy = (int(W * 0.62), int(H * (0.30 if cfg["title"] else 0.24)))

    lines = wrap(text, font, tw)
    lh = int(font.size * 1.5)
    ty = int(H * 0.28) if cfg["title"] else max(int(H * 0.16),
                                                (H - lh * len(lines)) // 2)
    tot = sum(len(l) for l in lines) or 1
    base = base_img(W, H, cfg["title"], ft)
    n = max(int(dur * fps), 8)
    ae = int(n * 0.32) if art is not None else 0
    te = max(int(n * 0.90), ae + 2)

    out = os.path.join(wd, f"s{idx}.mp4")
    lg = os.path.join(wd, f"s{idx}.log")
    cmd = ["ffmpeg", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-"]
    cmd += ["-i", au] if have else \
        ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac",
            "-b:a", "128k", "-shortest", "-movflags", "+faststart", out]

    with open(lg, "w") as log:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        last, im = None, None
        try:
            for f in range(n):
                if ae and f < ae:
                    af, nc = (f + 1) / ae, 0
                else:
                    af = 1.0 if art is not None else 0.0
                    sp = max(1, te - ae)
                    nc = int(tot * min(1.0, (f - ae) / sp))
                key = (round(af, 3), nc)
                if key != last:
                    im = frame(base, art, axy, af, lines, font, nc, tx, ty, lh)
                    last = key
                im.save(p.stdin, format="JPEG", quality=88)
            p.stdin.close()
        except BrokenPipeError:
            pass
        p.wait()

    if p.returncode != 0 or not os.path.exists(out):
        with open(lg) as log:
            st.error("FFmpeg সমস্যা:\n" + log.read()[-1200:])
        return None
    return out


def join(parts, wd):
    lst = os.path.join(wd, "list.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    fin = os.path.join(wd, "final.mp4")
    b = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst]
    r = subprocess.run(b + ["-c", "copy", "-movflags", "+faststart", fin],
                       capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(b + ["-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "25", "-c:a", "aac",
                                "-movflags", "+faststart", fin],
                           capture_output=True, text=True)
    if r.returncode != 0:
        st.error("জোড়া লাগাতে সমস্যা:\n" + r.stderr[-1200:])
        return None
    return fin


st.title("হোয়াইটবোর্ড ভিডিও মেকার")
st.caption("প্রতি লাইনের ছবি নিজে থেকেই তৈরি হবে। নির্দিষ্ট ছবি চাইলে "
           "লাইনের শেষে | দিয়ে ইংরেজিতে বিষয় লিখুন।")

title = st.text_input("শিরোনাম (ঐচ্ছিক)", "")
script = st.text_area("স্ক্রিপ্ট — প্রতি লাইনে একটি দৃশ্য",
                      "গাছ আমাদের অক্সিজেন দেয়\n"
                      "সূর্যের আলো থেকে গাছ খাদ্য তৈরি করে\n"
                      "তাই বেশি বেশি গাছ লাগানো দরকার", height=170)

mode = st.radio("ছবির ধরন",
                ["আইকন", "আইকন না পেলে AI", "AI ছবি", "ছবি ছাড়া"], index=1)
vname = st.selectbox("ভয়েস", list(VOICES.keys()))
speed = st.slider("কথার গতি (%)", -40, 40, 0, 5)
qual = st.radio("রেজোলিউশন", ["720p", "1080p"], horizontal=True)
with st.expander("আরও সেটিং"):
    fps = st.select_slider("ফ্রেম রেট", [8, 10, 12, 15], value=10)
    fsz = st.slider("লেখার আকার", 30, 80, 46, 2)
    pause = st.slider("দৃশ্যের শেষে বিরতি (সেকেন্ড)", 0.0, 2.0, 0.6, 0.2)
    upf = st.file_uploader("নিজের ফন্ট (.ttf)", type=["ttf", "otf"])

if st.button("ভিডিও তৈরি করুন", type="primary", use_container_width=True):
    sc = [s.strip() for s in script.splitlines() if s.strip()]
    if not sc:
        st.warning("অন্তত একটি লাইন লিখুন।")
        st.stop()
    if not shutil.which("ffmpeg"):
        st.error("ffmpeg নেই। packages.txt দেখে অ্যাপ Reboot করুন।")
        st.stop()

    W, H = (1280, 720) if qual == "720p" else (1920, 1080)
    k = H / 1080.0
    wd = tempfile.mkdtemp(prefix="wb_")
    up = None
    if upf is not None:
        up = os.path.join(wd, "user.ttf")
        with open(up, "wb") as f:
            f.write(upf.read())

    font = load_font(max(14, int(fsz * 1.9 * k)), up)
    ft = load_font(max(16, int(fsz * 2.3 * k)), up)
    if isinstance(font, ImageFont.ImageFont):
        st.warning("বাংলা ফন্ট পাওয়া যায়নি — 'আরও সেটিং' থেকে ফন্ট দিন।")

    cfg = dict(W=W, H=H, fps=fps, voice=VOICES[vname], rate=f"{speed:+d}%",
               title=title.strip(), pause=pause, mode=mode)
    box = int(H * 0.42)

    bar = st.progress(0.0, text="শুরু হচ্ছে...")
    parts = []
    for i, s in enumerate(sc):
        bar.progress(i / len(sc), text=f"দৃশ্য {i+1}/{len(sc)}...")
        r = scene(s, i, cfg, wd, font, ft, box)
        if r is None:
            st.stop()
        parts.append(r)

    bar.progress(0.96, text="জোড়া লাগানো হচ্ছে...")
    fin = parts[0] if len(parts) == 1 else join(parts, wd)
    if not fin:
        st.stop()
    bar.progress(1.0, text="সম্পন্ন")
    with open(fin, "rb") as f:
        st.session_state["vid"] = f.read()

if st.session_state.get("vid"):
    st.success("ভিডিও তৈরি হয়েছে।")
    st.video(st.session_state["vid"])
    st.download_button("ডাউনলোড (MP4)", st.session_state["vid"],
                       file_name="whiteboard.mp4", mime="video/mp4",
                       use_container_width=True)

with st.expander("Diagnostics"):
    st.write("ffmpeg:", shutil.which("ffmpeg"))
    st.write("font:", font_path())
    st.write("python:", sys.version.split()[0])
    try:
        import cairosvg
        st.write("cairosvg: OK")
    except Exception as e:
        st.write("cairosvg fail:", e)
    try:
        import edge_tts
        st.write("edge-tts: OK")
    except Exception as e:
        st.write("edge-tts fail:", e)
