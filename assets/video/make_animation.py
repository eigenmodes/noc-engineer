import math, os, random, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W = H = 1080
FPS = 30
BG = (10, 7, 5)
ACC = (255, 122, 26)
CREAM = (246, 235, 221)
MUTED = (205, 185, 164)
CARD = (33, 21, 13)
BORDER = (74, 42, 20)
RED = (224, 64, 42)
GREEN = (60, 200, 120)
HE_B = '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf'
HE_R = '/usr/share/fonts/truetype/freefont/FreeSans.ttf'
EN_B = '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf'
LOGO = '/home/claude/noc-engineer/assets/images/rafiki-logo-512.png'

_fc = {}
def font(path, size):
    k = (path, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    return _fc[k]

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease(x): x = clamp(x); return 1 - (1 - x) ** 3
def inout(x): x = clamp(x); return x * x * (3 - 2 * x)
def prog(t, start, dur): return ease((t - start) / dur)
def mix(c1, c2, k): return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))

# ---- static background: faint binary grid ----
def make_bg():
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    f = font(EN_B, 26)
    rnd = random.Random(7)
    for row in range(0, H, 44):
        for col in range(0, W, 30):
            if rnd.random() < 0.55:
                a = rnd.choice([14, 18, 24, 30])
                d.text((col + 6, row + 8), rnd.choice('01'), font=f, fill=(a + 10, a // 2, 4))
    # vignette
    v = Image.new('L', (W, H), 0)
    vd = ImageDraw.Draw(v)
    vd.ellipse((-200, -200, W + 200, H + 200), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(im, Image.new('RGB', (W, H), BG), v)
BGIMG = make_bg()

def rounded_logo(size):
    lg = Image.open(LOGO).convert('RGBA').resize((size, size), Image.LANCZOS)
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    lg.putalpha(m)
    return lg
LOGO_CACHE = {}
def logo(size):
    size = max(8, int(size))
    if size not in LOGO_CACHE: LOGO_CACHE[size] = rounded_logo(size)
    return LOGO_CACHE[size]

class Frame:
    def __init__(self):
        self.im = BGIMG.copy().convert('RGBA')
    def layer(self):
        return Image.new('RGBA', (W, H), (0, 0, 0, 0))
    def put(self, lay, alpha=1.0):
        if alpha <= 0: return
        if alpha < 1:
            a = lay.getchannel('A').point(lambda v: int(v * alpha))
            lay.putalpha(a)
        self.im.alpha_composite(lay)
    def text(self, xy, s, size, fill=CREAM, bold=True, he=True, anchor='mm', alpha=1.0):
        lay = self.layer(); d = ImageDraw.Draw(lay)
        f = font(HE_B if bold else HE_R, size) if he else font(EN_B, size)
        kw = {'direction': 'rtl', 'language': 'he'} if he else {}
        d.text(xy, s, font=f, fill=fill, anchor=anchor, **kw)
        self.put(lay, alpha)
    def rrect(self, box, r, fill, outline=None, width=2, alpha=1.0):
        lay = self.layer(); d = ImageDraw.Draw(lay)
        d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)
        self.put(lay, alpha)
    def logo(self, cx, cy, size, alpha=1.0, ring=True):
        lay = self.layer()
        if ring:
            ImageDraw.Draw(lay).rounded_rectangle((cx - size / 2 - 5, cy - size / 2 - 5, cx + size / 2 + 5, cy + size / 2 + 5), radius=int(size / 5) + 4, fill=ACC)
        lg = logo(size)
        lay.alpha_composite(lg, (int(cx - lg.width / 2), int(cy - lg.height / 2)))
        self.put(lay, alpha)
    def glow(self, cx, cy, r, color, alpha=1.0):
        lay = self.layer()
        ImageDraw.Draw(lay).ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (150,))
        lay = lay.filter(ImageFilter.GaussianBlur(r / 2.2))
        self.put(lay, alpha)
    def rgb(self, fade):
        out = self.im.convert('RGB')
        if fade < 1:
            out = Image.blend(Image.new('RGB', (W, H), BG), out, clamp(fade))
        return out

def scene_fade(t, dur, fin=0.35, fout=0.35):
    return min(clamp(t / fin), clamp((dur - t) / fout))

def caption(fr, s, t, start=0.2):
    k = prog(t, start, 0.5)
    fr.text((W / 2, 1000 - 20 * (1 - k)), s, 40, MUTED, bold=False, alpha=k)

def small_header(fr, t):
    k = prog(t, 0, 0.4)
    fr.logo(470, 90, 76, alpha=k)
    fr.text((520, 90), 'Rafiki', 46, CREAM, he=False, anchor='lm', alpha=k)

# ---------------- scenes ----------------
def s1(fr, t):  # 3.5s logo intro
    # meteor streak
    k = prog(t, 0.0, 1.0)
    sx, sy = 1150, -120
    ex, ey = W / 2, 420
    x = sx + (ex - sx) * k; y = sy + (ey - sy) * k
    if t < 1.3:
        lay = fr.layer(); d = ImageDraw.Draw(lay)
        for i in range(26):
            q = i / 26
            px = x + (sx - ex) * 0.35 * q; py = y + (sy - ey) * 0.35 * q
            rr = 34 * (1 - q)
            d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=mix(ACC, (255, 210, 90), q) + (int(220 * (1 - q)),))
        lay = lay.filter(ImageFilter.GaussianBlur(6))
        fr.put(lay, clamp((1.3 - t) / 0.3))
    kl = prog(t, 0.8, 0.7)
    if kl > 0:
        fr.glow(W / 2, 420, 260, ACC, alpha=0.35 * kl)
        fr.logo(W / 2, 420, 300 * (0.6 + 0.4 * kl), alpha=kl)
    kw = prog(t, 1.4, 0.6)
    lay = fr.layer(); d = ImageDraw.Draw(lay)
    f = font(EN_B, 120)
    w1 = d.textlength('Raf', font=f); w2 = d.textlength('iki', font=f)
    x0 = W / 2 - (w1 + w2) / 2
    yy = 690 + 30 * (1 - kw)
    d.text((x0, yy), 'Raf', font=f, fill=CREAM, anchor='lm')
    d.text((x0 + w1, yy), 'iki', font=f, fill=ACC, anchor='lm')
    fr.put(lay, kw)
    kt = prog(t, 2.0, 0.6)
    if kt > 0:
        yy = 830 + 30 * (1 - kt)
        fr.rrect((230, yy - 34, 370, yy + 34), 34, ACC, alpha=kt)
        fr.text((300, yy + 2), '24/7', 40, (20, 12, 7), he=False, alpha=kt)
        fr.text((870, yy), 'הסוכן התורן שלכם', 50, CREAM, anchor='rm', alpha=kt)

def s2(fr, t):  # 4s incoming request
    small_header(fr, t)
    ka = prog(t, 0.2, 0.5)
    pulse = 0.5 + 0.5 * math.sin(t * 6)
    if ka > 0:
        fr.glow(W / 2, 330, 70, RED, alpha=0.5 * ka * pulse)
        lay = fr.layer(); d = ImageDraw.Draw(lay)
        cx, cy = W / 2, 330
        d.polygon([(cx, cy - 56), (cx + 62, cy + 48), (cx - 62, cy + 48)], fill=RED)
        d.rectangle((cx - 6, cy - 22, cx + 6, cy + 16), fill=CREAM)
        d.ellipse((cx - 7, cy + 26, cx + 7, cy + 40), fill=CREAM)
        fr.put(lay, ka)
        fr.text((W / 2, 430), 'התראה חדשה', 40, RED, alpha=ka)
    kb = prog(t, 1.0, 0.6)
    if kb > 0:
        dx = 60 * (1 - kb)
        fr.rrect((80 + dx, 540, 980 + dx, 740), 30, CARD, outline=BORDER, alpha=kb)
        # avatar
        lay = fr.layer(); ImageDraw.Draw(lay).ellipse((910 + dx - 32, 588, 910 + dx + 32, 652), fill=(90, 70, 55))
        fr.put(lay, kb)
        fr.text((910 + dx, 620), 'ל', 36, CREAM, alpha=kb)
        fr.text((860 + dx, 620), 'לקוח', 34, MUTED, bold=False, anchor='rm', alpha=kb)
        msg_k = prog(t, 1.5, 1.2)
        full = 'יש לנו ירידה בתוצר מהבוקר, מה קורה?'
        n = int(len(full) * msg_k)
        ew = ImageDraw.Draw(Image.new('RGB', (1, 1))).textlength('@Rafiki', font=font(EN_B, 32))
        fr.text((930 + dx, 692), '@Rafiki', 32, ACC, he=False, anchor='rm', alpha=kb)
        fr.text((930 + dx - ew - 12, 690), full[:n], 34, CREAM, anchor='rm', alpha=kb)
    caption(fr, 'פונים אליו בצ\'אט, בלי טפסים', t, 2.2)

def d_len(s, size):
    if not s: return 0
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    return d.textlength(s, font=font(HE_B, size), direction='rtl', language='he')

def s3(fr, t):  # 5s scanning sources
    small_header(fr, t)
    fr.text((W / 2, 260), 'סורק את כל מקורות המידע', 54, CREAM, alpha=prog(t, 0.1, 0.5))
    items = [('מטריקות', 'chart'), ('לוגים', 'logs'), ('מערכות', 'server')]
    for i, (name, kind) in enumerate(items):
        st = 0.6 + i * 0.9
        k = prog(t, st, 0.5)
        if k <= 0: continue
        cx = 820 - i * 280; cy = 580 + 30 * (1 - k)
        fr.rrect((cx - 120, cy - 150, cx + 120, cy + 150), 26, CARD, outline=BORDER, alpha=k)
        lay = fr.layer(); d = ImageDraw.Draw(lay)
        if kind == 'chart':
            for j, hgt in enumerate([40, 70, 55, 95, 80]):
                x = cx - 80 + j * 34
                d.rectangle((x, cy - 10 - hgt, x + 22, cy - 10), fill=ACC)
        elif kind == 'logs':
            for j, ln in enumerate([150, 110, 170, 90, 130]):
                d.rounded_rectangle((cx + 85 - ln, cy - 110 + j * 20, cx + 85, cy - 100 + j * 20), radius=5, fill=MUTED if j != 3 else ACC)
        else:
            for j in range(3):
                y = cy - 115 + j * 36
                d.rounded_rectangle((cx - 70, y, cx + 70, y + 28), radius=6, outline=MUTED, width=3)
                d.ellipse((cx + 42, y + 9, cx + 54, y + 21), fill=GREEN if j != 1 else ACC)
        fr.put(lay, k)
        fr.text((cx, cy + 50), name, 40, CREAM, alpha=k)
        pk = prog(t, st + 0.3, 1.0)
        fr.rrect((cx - 90, cy + 100, cx + 90, cy + 114), 7, BORDER, alpha=k)
        if pk > 0.02:
            fr.rrect((cx + 90 - 180 * pk, cy + 100, cx + 90, cy + 114), 7, ACC, alpha=k)
    caption(fr, 'מטריקות, לוגים ומערכות, ברציפות', t, 3.4)

def s4(fr, t):  # 5s locating the hop
    small_header(fr, t)
    fr.text((W / 2, 260), 'מאתר את מקור התקלה', 54, CREAM, alpha=prog(t, 0.1, 0.5))
    labels = ['לקוח', 'הופ 1', 'הופ 2', 'הופ 3', 'שרת']
    xs = [900, 720, 540, 360, 180]; y = 620
    lk = prog(t, 0.5, 1.6)
    lay = fr.layer(); d = ImageDraw.Draw(lay)
    total = xs[0] - xs[-1]
    d.line((xs[0], y, xs[0] - total * lk, y), fill=MUTED, width=6)
    fr.put(lay)
    bad = prog(t, 2.4, 0.4)
    for i, (x, lab) in enumerate(zip(xs, labels)):
        k = prog(t, 0.5 + i * 0.32, 0.35)
        if k <= 0: continue
        is_bad = i == 3
        col = mix(GREEN, RED, bad) if is_bad else GREEN
        if is_bad and bad > 0:
            p = 0.5 + 0.5 * math.sin(t * 7)
            fr.glow(x, y, 70, RED, alpha=0.7 * bad * p)
        lay = fr.layer(); d = ImageDraw.Draw(lay)
        r = 34 * k
        d.ellipse((x - r, y - r, x + r, y + r), fill=CARD, outline=col, width=7)
        fr.put(lay)
        fr.text((x, y + 80), lab, 36, CREAM if not (is_bad and bad > 0.5) else RED, alpha=k)
    ck = prog(t, 2.9, 0.5)
    if ck > 0:
        bx, by = 360, 450 - 20 * (1 - ck)
        fr.rrect((bx - 210, by - 46, bx + 210, by + 46), 22, RED, alpha=ck)
        fr.text((bx, by + 2), 'ירידה בתוצר מ-08:40', 38, CREAM, alpha=ck)
        lay = fr.layer(); ImageDraw.Draw(lay).polygon([(bx - 16, by + 46), (bx + 16, by + 46), (bx, by + 70)], fill=RED)
        fr.put(lay, ck)
    caption(fr, 'הופ, חוק, שרת, וזמן התחלה', t, 3.4)

def s5(fr, t):  # 5s answer + ticket
    small_header(fr, t)
    k = prog(t, 0.2, 0.6)
    if k > 0:
        dx = -60 * (1 - k)
        fr.rrect((90 + dx, 200, 960 + dx, 470), 30, CARD, outline=ACC, alpha=k)
        fr.logo(170 + dx, 270, 80, alpha=k, ring=False)
        fr.text((900 + dx, 260), 'מצאתי: ירידה בתוצר בהופ 3', 42, CREAM, anchor='rm', alpha=k)
        fr.text((900 + dx, 320), 'התחילה ב-08:40. מצרף ראיות:', 36, MUTED, bold=False, anchor='rm', alpha=k)
        for i, chip in enumerate(['גרף', 'לוג', 'שאילתה']):
            ck = prog(t, 0.9 + i * 0.25, 0.4)
            cx = 820 - i * 180 + dx
            fr.rrect((cx - 75, 370, cx + 75, 430), 30, (60, 32, 14), outline=ACC, alpha=ck)
            fr.text((cx, 401), chip, 34, ACC, alpha=ck)
    jk = prog(t, 1.9, 0.6)
    if jk > 0:
        y0 = 560 + 40 * (1 - jk)
        fr.rrect((200, y0, 880, y0 + 250), 26, CARD, outline=BORDER, alpha=jk)
        fr.text((820, y0 + 60), 'קריאה ב-Jira', 40, CREAM, anchor='rm', alpha=jk)
        fr.text((820, y0 + 115), 'הממצאים תועדו בקריאה', 34, MUTED, bold=False, anchor='rm', alpha=jk)
        sk = prog(t, 3.0, 0.4)
        col = mix((90, 70, 55), GREEN, sk)
        fr.rrect((260, y0 + 160, 560, y0 + 220), 30, col, alpha=jk)
        txt = 'טופלה ונסגרה' if sk > 0.5 else 'בבדיקה'
        fr.text((410, y0 + 191), txt, 34, (15, 10, 6) if sk > 0.5 else CREAM, alpha=jk)
        if sk > 0.5:
            lay = fr.layer(); d = ImageDraw.Draw(lay)
            d.line([(820 - 640, y0 + 190), (820 - 625, y0 + 205), (820 - 598, y0 + 172)], fill=GREEN, width=8)
            fr.put(lay, jk)
    caption(fr, 'עונה עם ראיות, ומטפל או מעביר לצוות', t, 3.3)

def s6(fr, t):  # 4s daily report + end
    if t < 2.2:
        a = clamp((2.2 - t) / 0.3)
        small_header(fr, t)
        k = prog(t, 0.1, 0.5)
        fr.rrect((180, 260, 900, 720), 30, CARD, outline=BORDER, alpha=k * a)
        fr.text((840, 330), 'דוח יומי', 50, CREAM, anchor='rm', alpha=k * a)
        fr.rrect((250, 300, 400, 360), 30, ACC, alpha=k * a)
        fr.text((325, 331), '09:00', 36, (20, 12, 7), he=False, alpha=k * a)
        rows = ['מה חרג', 'מה טופל', 'מה עדיין פתוח']
        for i, r in enumerate(rows):
            rk = prog(t, 0.5 + i * 0.25, 0.4) * a
            y = 450 + i * 85
            fr.text((800, y), r, 42, CREAM, bold=False, anchor='rm', alpha=rk)
            lay = fr.layer(); ImageDraw.Draw(lay).ellipse((830, y - 14, 858, y + 14), fill=[RED, GREEN, ACC][i])
            fr.put(lay, rk)
        caption(fr, 'וכל בוקר, סיכום מסודר לצוות', t, 0.6)
    else:
        u = t - 2.2
        k = prog(u, 0, 0.6)
        fr.glow(W / 2, 400, 230, ACC, alpha=0.3 * k)
        fr.logo(W / 2, 400, 260 * (0.85 + 0.15 * k), alpha=k)
        lay = fr.layer(); d = ImageDraw.Draw(lay)
        f = font(EN_B, 96)
        s = '@Rafiki'
        w = d.textlength(s, font=f)
        d.text((W / 2 - w / 2, 640), '@Raf', font=f, fill=CREAM, anchor='lm')
        d.text((W / 2 - w / 2 + d.textlength('@Raf', font=f), 640), 'iki', font=f, fill=ACC, anchor='lm')
        fr.put(lay, k)
        k2 = prog(u, 0.4, 0.6)
        fr.rrect((230, 740, 370, 808), 34, ACC, alpha=k2)
        fr.text((300, 776), '24/7', 40, (20, 12, 7), he=False, alpha=k2)
        fr.text((870, 774), 'הסוכן התורן שלכם', 50, CREAM, anchor='rm', alpha=k2)

SCENES = [('s1', s1, 3.5), ('s2', s2, 4.0), ('s3', s3, 5.0), ('s4', s4, 5.0), ('s5', s5, 5.0), ('s6', s6, 4.6)]

def render_frame(fn, t, dur, first=False, last=False):
    fr = Frame(); fn(fr, t)
    fin = 0.001 if first else 0.35
    return fr.rgb(scene_fade(t, dur, fin=fin, fout=0.6 if last else 0.35))

if __name__ == '__main__':
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    if len(sys.argv) > 2 and sys.argv[2] == 'stills':
        for name, fn, dur in SCENES:
            for tt in ((1.5,) if name == 's6' else ()) + (dur * 0.5, dur - 0.5):
                render_frame(fn, tt, dur).save(f'{out}/{name}_{tt:.1f}.png')
        sys.exit()
    files = []
    for i, (name, fn, dur) in enumerate(SCENES):
        tmp = f'{out}/{name}.tmp.mp4'; fin = f'{out}/{name}.mp4'
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
        n = int(round(dur * FPS))
        for f in range(n):
            p.stdin.write(render_frame(fn, f / FPS, dur, first=(i == 0), last=(i == len(SCENES) - 1)).tobytes())
        p.stdin.close()
        assert p.wait() == 0
        os.replace(tmp, fin); files.append(fin); print('done', name, flush=True)
    with open(f'{out}/list.txt', 'w') as fl:
        for f in files: fl.write(f"file '{os.path.abspath(f)}'\n")
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', f'{out}/list.txt', '-c', 'copy', '-movflags', '+faststart', f'{out}/rafiki.mp4'], check=True)
    print('final', f'{out}/rafiki.mp4')
