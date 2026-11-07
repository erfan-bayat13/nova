"""Build local test videos (no downloads, no screen-recording permission needed).

videos/camera.mp4  – real photos with a slow camera-style zoom + a spoken voice-over (`say`)
videos/screen.mp4  – a phone screen: timer counting down → recipe app → message notification
videos/museum.mp4  – a phone camera panning across a museum placard
"""
import os, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "videos")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP = tempfile.mkdtemp(prefix="vid_", dir=OUT)


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def shot(html, path, w=390, h=844):
    src = os.path.join(TMP, os.path.basename(path) + ".html")
    open(src, "w").write(html)
    run(CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
        f"--screenshot={path}", f"file://{src}")


PHONE_CSS = """<style>body{margin:0;width:390px;height:844px;font-family:-apple-system,Helvetica,sans-serif;
background:#f2f2f7;color:#111;overflow:hidden;position:relative}
.bar{height:44px;display:flex;justify-content:space-between;align-items:center;padding:0 24px;font-weight:600;font-size:15px}
.big{font-size:84px;font-weight:300;text-align:center;margin-top:160px;font-variant-numeric:tabular-nums}
.sub{text-align:center;color:#666;font-size:20px}
.card{background:#fff;margin:16px;border-radius:14px;padding:18px;font-size:18px;line-height:1.5}
h1{margin:12px 20px 0;font-size:32px}
.notif{position:absolute;top:52px;left:10px;right:10px;background:rgba(255,255,255,.97);border-radius:18px;
padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.25);font-size:16px}
</style>"""


def camera_video():
    imgs = []
    for name in ("Penguin", "Zebra", "Parrot"):
        jpg = os.path.join(TMP, f"{name}.jpg")
        run("sips", "-s", "format", "jpeg", "-Z", "1024", f"/Library/User Pictures/Animals/{name}.heic", "--out", jpg)
        imgs.append(jpg)
    vo = os.path.join(TMP, "vo.aiff")
    run("say", "-o", vo, "Okay, first we have this little guy. Then this striped one. "
                         "And finally, the colorful one is my favorite.")
    # each photo 4 s with a slow zoom-in, 640x640, then concat + voice-over
    parts = []
    for i, img in enumerate(imgs):
        p = os.path.join(TMP, f"cam{i}.mp4")
        run("ffmpeg", "-y", "-loop", "1", "-i", img, "-t", "4", "-vf",
            "scale=1280:1280,zoompan=z='min(zoom+0.0015,1.25)':d=100:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=640x640:fps=25",
            "-pix_fmt", "yuv420p", p)
        parts.append(p)
    lst = os.path.join(TMP, "cam.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", vo, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-af", "apad", "-t", "12", os.path.join(OUT, "camera.mp4"))


def screen_video():
    frames = []
    # 1) timer counting down 05:00 → 04:56
    for s in range(5):
        t = f"04:{60 - s:02d}" if s else "05:00"
        frames.append((PHONE_CSS + f'<div class="bar"><span>9:41</span><span>Timer</span></div>'
                       f'<div class="big">{t}</div><div class="sub">Pasta</div>', 1))
    recipe = (PHONE_CSS + '<div class="bar"><span>9:41</span><span>Recipes</span></div><h1>Spaghetti Carbonara</h1>'
              '<div class="card"><b>Serves 4</b> · 25 min<br>400 g spaghetti<br>150 g pancetta<br>3 eggs<br>'
              '50 g parmesan<br>Black pepper</div>')
    frames.append((recipe, 3))
    frames.append((recipe + '<div class="notif"><b>Mom</b> · now<br>Dinner at 7? Bring dessert please 🍰</div>', 3))
    pngs = []
    for i, (html, secs) in enumerate(frames):
        p = os.path.join(TMP, f"scr{i}.png")
        shot("<meta charset=utf-8>" + html, p)
        pngs.append((p, secs))
    lst = os.path.join(TMP, "scr.txt")
    open(lst, "w").write("".join(f"file '{p}'\nduration {s}\n" for p, s in pngs) + f"file '{pngs[-1][0]}'\n")
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf", "fps=25,format=yuv420p",
        "-c:v", "libx264", os.path.join(OUT, "screen.mp4"))


def museum_video():
    html = ("<meta charset=utf-8><style>body{margin:0;width:1400px;height:1000px;background:#d9d2c5;"
            "font-family:Georgia,serif;display:flex;align-items:center;gap:60px;padding:80px;box-sizing:border-box}"
            ".art{width:560px;height:700px;background:linear-gradient(160deg,#1b2a6b,#3b5bb5 40%,#f2c94c 41%,#1b2a6b 45%,#0d1640);"
            "border:24px solid #6b4f2a;box-shadow:0 10px 40px rgba(0,0,0,.4)}"
            ".plaque{background:#f7f3ea;padding:40px;width:520px;border-radius:4px;box-shadow:0 4px 14px rgba(0,0,0,.2);color:#222}"
            "h2{margin:0 0 8px;font-size:40px}.meta{font-size:22px;color:#555;margin-bottom:20px}p{font-size:22px;line-height:1.5}"
            "</style><div class=art></div><div class=plaque><h2>Night Harbor</h2>"
            "<div class=meta>Elena Varga · 1912 · Oil on canvas</div>"
            "<p>Painted during a winter storm in Trieste, this work shows the harbor lights reflected in "
            "rough water. Varga used a single streak of yellow to suggest the lighthouse beam.</p>"
            "<p>Gift of the Morel Family, 1968.</p></div>")
    png = os.path.join(TMP, "museum.png")
    shot(html, png, 1400, 1000)
    # handheld-style pan from the painting to the placard, 8 s
    run("ffmpeg", "-y", "-loop", "1", "-i", png, "-t", "8", "-vf",
        "zoompan=z='1.6':d=200:x='(iw-iw/zoom)*on/200':y='ih/2-(ih/zoom/2)+10*sin(on/7)':s=720x540:fps=25,format=yuv420p",
        "-c:v", "libx264", os.path.join(OUT, "museum.mp4"))


if __name__ == "__main__":
    for fn in (camera_video, screen_video, museum_video):
        fn()
        print("made", fn.__name__)
    subprocess.run(["rm", "-rf", TMP])
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")
