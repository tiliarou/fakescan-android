"""
Fake Scan PDF - Android (Kivy)
================================
Dependances Python :
    pip install kivy pillow plyer

Compiler en APK :
    pip install buildozer
    buildozer android debug

Structure :
    MainScreen   -> selection fichiers, pages, effets, generation
    PickerScreen -> dessin des zones parafe/signature sur apercu PDF
"""

import io
import os
import random
import threading
import sys

# -- Kivy config (avant tout import kivy) ----------------------------------
from kivy.config import Config
Config.set("graphics", "width",  "400")
Config.set("graphics", "height", "750")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Line
from kivy.graphics.texture import Texture
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageChops

# -- Detection Android -----------------------------------------------------
ANDROID = sys.platform == "linux" and "ANDROID_ARGUMENT" in os.environ

if ANDROID:
    try:
        from jnius import autoclass
        HAS_JNIUS = True

        # -- Toutes les classes Java chargees UNE SEULE FOIS au demarrage --
        _File                 = autoclass("java.io.File")
        _ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")
        _PdfRenderer          = autoclass("android.graphics.pdf.PdfRenderer")
        _PdfRendererPage      = autoclass("android.graphics.pdf.PdfRenderer$Page")
        _Bitmap               = autoclass("android.graphics.Bitmap")
        _BitmapConfig         = autoclass("android.graphics.Bitmap$Config")
        _BitmapCompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
        _ByteArrayOS          = autoclass("java.io.ByteArrayOutputStream")
        _Color_java           = autoclass("android.graphics.Color")
        _Canvas_java          = autoclass("android.graphics.Canvas")

    except ImportError:
        HAS_JNIUS = False
    HAS_FITZ = False
else:
    HAS_JNIUS = False
    try:
        import fitz
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False


# -------------------------------------------------------------------------
# TRAITEMENT IMAGE PIL PUR
# -------------------------------------------------------------------------

def ensure_white_bg(img):
    """Si l'image a un canal alpha (RGBA/LA), composite sur fond blanc."""
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def _pil_grain_L(img, strength=4):
    w, h = img.size
    noise = Image.frombytes('L', (w, h), os.urandom(w * h))
    noise = noise.point(lambda x: int(x / 255 * (2 * strength)) - strength + 128)
    return ImageChops.add(img, noise, scale=1, offset=-128)


def _pil_grain_RGBA(img, strength=8):
    w, h = img.size
    r, g, b, a = img.split()
    noise = Image.frombytes('L', (w, h), os.urandom(w * h))
    noise = noise.point(lambda x: int(x / 255 * (2 * strength)) - strength + 128)
    mask = a.point(lambda x: 255 if x > 30 else 0)
    def _apply(ch):
        noisy = ImageChops.add(ch, noise, scale=1, offset=-128)
        return Image.composite(noisy, ch, mask)
    return Image.merge('RGBA', (_apply(r), _apply(g), _apply(b), a))


# -------------------------------------------------------------------------
# COULEURS / STYLES GLOBAUX
# -------------------------------------------------------------------------

C_BG        = (0.97, 0.97, 0.97, 1)
C_HEADER    = (0.18, 0.18, 0.22, 1)
C_GREEN     = (0.26, 0.63, 0.28, 1)
C_ORANGE    = (1.00, 0.60, 0.00, 1)
C_RED       = (0.80, 0.20, 0.20, 1)
C_GREY_BTN  = (0.88, 0.88, 0.88, 1)
C_WHITE     = (1, 1, 1, 1)
C_TEXT_DARK = (0.15, 0.15, 0.15, 1)

from kivy.metrics import dp, sp as _sp

FS_BTN     = "16sp"
FS_LABEL   = "15sp"
FS_SECTION = "17sp"
FS_INPUT   = "16sp"
FS_HEADER  = "20sp"
FS_POPUP   = "15sp"

H_BTN      = dp(48)
H_LABEL    = dp(36)
H_SECTION  = dp(40)
H_INPUT    = dp(48)
H_HEADER   = dp(56)
H_BTN_GEN  = dp(56)
H_SLIDER   = dp(48)
H_SPACER   = dp(16)

PAGE_GAP   = dp(8)   # espace entre pages dans le picker


def make_btn(text, bg=C_GREY_BTN, fg=C_TEXT_DARK, size_hint_x=1,
             height=H_BTN, bold=False, on_press=None):
    btn = Button(
        text=text,
        background_normal="",
        background_color=bg,
        color=fg,
        size_hint=(size_hint_x, None),
        height=height,
        bold=bold,
        font_size=FS_BTN,
    )
    if on_press:
        btn.bind(on_press=on_press)
    return btn


def make_label(text, color=C_TEXT_DARK, font_size=FS_LABEL,
               size_hint_y=None, height=H_LABEL, halign="left", italic=False):
    lbl = Label(
        text=text,
        color=color,
        font_size=font_size,
        size_hint_y=None,
        height=height,
        halign=halign,
        italic=italic,
    )
    lbl.bind(size=lambda inst, v: setattr(inst, "text_size", v))
    return lbl


def section_label(text):
    lbl = Label(
        text="[b]" + text + "[/b]",
        markup=True,
        color=C_HEADER,
        font_size=FS_SECTION,
        size_hint_y=None,
        height=H_SECTION,
        halign="left",
    )
    lbl.bind(size=lambda inst, v: setattr(inst, "text_size", v))
    return lbl


# -------------------------------------------------------------------------
# STRUCTURE RECT
# -------------------------------------------------------------------------

class Rect:
    def __init__(self, x1, y1, x2, y2):
        self.x1 = min(x1, x2)
        self.y1 = min(y1, y2)
        self.x2 = max(x1, x2)
        self.y2 = max(y1, y2)

    @property
    def w(self): return self.x2 - self.x1

    @property
    def h(self): return self.y2 - self.y1

    @property
    def valid(self): return self.w > 8 and self.h > 8

    def __repr__(self):
        return "Rect({},{}->{},{} [{}x{}])".format(
            self.x1, self.y1, self.x2, self.y2, self.w, self.h)


# -------------------------------------------------------------------------
# TRAITEMENT IMAGE
# -------------------------------------------------------------------------

def vary_signature(base_img):
    sig = base_img.copy()
    sig = sig.rotate(random.uniform(-1.2, 1.2), expand=True, fillcolor=(0, 0, 0, 0))
    sig = ImageEnhance.Contrast(sig).enhance(random.uniform(0.88, 1.12))
    sig = _pil_grain_RGBA(sig, strength=random.randint(4, 10))
    sig = sig.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.05, 0.55)))
    return sig


def fit_into_rect(img, rect, jitter=True):
    scale = min(rect.w / img.width, rect.h / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    img_r = img.resize((nw, nh), Image.LANCZOS)
    cx = rect.x1 + (rect.w - nw) // 2
    cy = rect.y1 + (rect.h - nh) // 2
    if jitter:
        cx += random.randint(-3, 3)
        cy += random.randint(-3, 3)
    return img_r, cx, cy


def simulate_scan(img, tilt=1.2, blur=0.3, contrast=1.1, brightness=1.0, grayscale=True):
    img = img.rotate(random.uniform(-tilt, tilt), expand=True, fillcolor=(255, 255, 255))
    if grayscale:
        img = ImageOps.grayscale(img)
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        img = _pil_grain_L(img, strength=4)
    else:
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        img = img.convert("RGB")
        r, g, b = img.split()
        r = _pil_grain_L(r, strength=3)
        g = _pil_grain_L(g, strength=3)
        b = _pil_grain_L(b, strength=3)
        img = Image.merge("RGB", (r, g, b))
    img = ImageEnhance.Contrast(img).enhance(contrast + random.uniform(-0.05, 0.05))
    img = ImageEnhance.Brightness(img).enhance(brightness + random.uniform(-0.02, 0.02))
    w, h = img.size
    img = img.resize((int(w * 0.95), int(h * 0.95)), Image.LANCZOS)
    img = img.resize((w, h), Image.LANCZOS)
    return img


def parse_pages(text, total_pages):
    pages = set()
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                for p in range(int(a), int(b) + 1):
                    if 1 <= p <= total_pages:
                        pages.add(p)
            except ValueError:
                pass
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.add(p)
            except ValueError:
                pass
    return sorted(pages)


# -------------------------------------------------------------------------
# PDF HELPERS
# -------------------------------------------------------------------------

DPI_PREVIEW = 100
DPI_PROCESS = 250


def _android_render_page(renderer, page_index, dpi):
    """
    Rend une page depuis un PdfRenderer DEJA OUVERT.
    NE ferme PAS le renderer. Retourne une PIL Image RGB.
    Utilise les classes Java pre-chargees au niveau module.
    """
    page   = renderer.openPage(page_index)
    scale  = dpi / 72.0
    width  = int(page.getWidth()  * scale)
    height = int(page.getHeight() * scale)

    bitmap = _Bitmap.createBitmap(width, height, _BitmapConfig.ARGB_8888)
    canvas = _Canvas_java(bitmap)
    canvas.drawColor(_Color_java.WHITE)
    # RENDER_MODE_FOR_PRINT (1) est plus stable que FOR_DISPLAY (0)
    # sur les PDFs complexes (evite l'erreur "Invalid ID")
    page.render(bitmap, None, None, _PdfRendererPage.RENDER_MODE_FOR_PRINT)
    page.close()   # fermer la PAGE (obligatoire avant d'en ouvrir une autre)

    baos = _ByteArrayOS()
    bitmap.compress(_BitmapCompressFormat.PNG, 100, baos)
    img = Image.open(io.BytesIO(bytes(baos.toByteArray())))
    return ensure_white_bg(img)


def _android_open_renderer(pdf_path):
    """Ouvre et retourne (renderer, pfd) pour pdf_path. A fermer apres usage."""
    pfd      = _ParcelFileDescriptor.open(_File(pdf_path), _ParcelFileDescriptor.MODE_READ_ONLY)
    renderer = _PdfRenderer(pfd)
    return renderer, pfd


def _android_pdf_page_count(pdf_path):
    renderer, pfd = _android_open_renderer(pdf_path)
    count = renderer.getPageCount()
    renderer.close()
    pfd.close()
    return count


def _android_pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW):
    """Rend une seule page (ouvre/ferme le renderer). Usage : apercu page unique."""
    renderer, pfd = _android_open_renderer(pdf_path)
    try:
        img = _android_render_page(renderer, page_index, dpi)
    finally:
        renderer.close()
        pfd.close()
    return img


def _android_pdf_all_pages(pdf_path, dpi):
    """
    Rend TOUTES les pages en ouvrant le renderer UNE SEULE FOIS.
    Corrige l'erreur 'Invalid ID' qui survenait quand on ouvrait
    un renderer par page.
    """
    renderer, pfd = _android_open_renderer(pdf_path)
    images = []
    try:
        count = renderer.getPageCount()
        for i in range(count):
            images.append(_android_render_page(renderer, i, dpi))
    finally:
        renderer.close()
        pfd.close()
    return images


def pdf_page_count(pdf_path):
    if ANDROID and HAS_JNIUS:
        return _android_pdf_page_count(pdf_path)
    elif HAS_FITZ:
        doc = fitz.open(pdf_path)
        n = len(doc)
        doc.close()
        return n
    return 999


def pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW):
    if ANDROID and HAS_JNIUS:
        return _android_pdf_page_to_pil(pdf_path, page_index, dpi)
    elif HAS_FITZ:
        doc  = fitz.open(pdf_path)
        page = doc[page_index]
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    raise RuntimeError("Aucun moteur PDF disponible")


def pdf_to_pil_list(pdf_path, dpi=DPI_PROCESS):
    """Rend toutes les pages a haute resolution (generation finale)."""
    if ANDROID and HAS_JNIUS:
        # Renderer ouvert une seule fois pour toutes les pages
        return _android_pdf_all_pages(pdf_path, dpi)
    elif HAS_FITZ:
        doc    = fitz.open(pdf_path)
        mat    = fitz.Matrix(dpi / 72, dpi / 72)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        doc.close()
        return images
    raise RuntimeError("Aucun moteur PDF disponible")


def pdf_preview_all_pages(pdf_path, dpi=DPI_PREVIEW):
    """Rend toutes les pages a basse resolution pour la previsualisation."""
    if ANDROID and HAS_JNIUS:
        # Renderer ouvert une seule fois pour toutes les pages
        return _android_pdf_all_pages(pdf_path, dpi)
    elif HAS_FITZ:
        doc    = fitz.open(pdf_path)
        mat    = fitz.Matrix(dpi / 72, dpi / 72)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            images.append(ensure_white_bg(
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
        doc.close()
        return images
    raise RuntimeError("Aucun moteur PDF disponible")


def pil_list_to_pdf(images, out):
    if not images:
        return
    rgb = [img.convert("RGB") for img in images]
    rgb[0].save(out, format="PDF", save_all=True,
                append_images=rgb[1:], resolution=DPI_PROCESS)


def pil_to_kivy_texture(pil_img):
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data    = pil_img.tobytes()
    texture = Texture.create(size=(pil_img.width, pil_img.height), colorfmt="rgba")
    texture.blit_buffer(data, colorfmt="rgba", bufferfmt="ubyte")
    texture.flip_vertical()
    return texture


# -------------------------------------------------------------------------
# WIDGET : CANVAS MULTI-PAGES SCROLLABLE (PickerCanvas)
# -------------------------------------------------------------------------

class PickerCanvas(Widget):
    """
    Affiche toutes les pages PDF empilees verticalement.
    Encapsulee dans un ScrollView pour le defilement.
    Le dessin de rectangles se fait sur la page touchee.
    """

    COLOR_PARAFE = (0.62, 0.14, 0.80, 0.45)
    COLOR_SIG    = (0.18, 0.63, 0.18, 0.45)
    OUTLINE_P    = (0.62, 0.14, 0.80, 1.0)
    OUTLINE_S    = (0.18, 0.63, 0.18, 1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode           = None
        self.pages          = []
        self.dpi_ratio      = DPI_PROCESS / DPI_PREVIEW
        self._rects         = {}
        self._rects_canvas  = {}
        self._drag_start    = None
        self._drag_page_idx = None
        self._drag_geom     = None
        self._live_coords   = None
        self._page_geom     = []
        self.bind(size=self._redraw, pos=self._redraw)

    def set_pages(self, pages):
        self.pages = pages
        self._rects        = {i: {"parafe": None, "sig": None} for i in range(len(pages))}
        self._rects_canvas = {i: {"parafe": None, "sig": None} for i in range(len(pages))}
        self._update_height()
        self._redraw()

    def _update_height(self):
        if not self.pages:
            self.height = dp(200)
            return
        avail_w = self.width if self.width > 1 else Window.width
        total_h = 0
        for img in self.pages:
            scale   = avail_w / img.width
            total_h += int(img.height * scale) + PAGE_GAP
        self.height = total_h

    def _redraw(self, *_):
        self.canvas.clear()
        if not self.pages:
            return
        self._update_height()
        avail_w = self.width if self.width > 1 else Window.width
        self._page_geom = []
        cursor_y = self.height
        for idx, img in enumerate(self.pages):
            scale    = avail_w / img.width
            dw       = int(img.width  * scale)
            dh       = int(img.height * scale)
            cursor_y -= dh
            x_off = self.x + (avail_w - dw) / 2
            y_off = self.y + cursor_y
            self._page_geom.append((x_off, y_off, dw, dh, scale))
            tex = pil_to_kivy_texture(img)
            with self.canvas:
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(x_off, y_off), size=(dw, dh))
            cursor_y -= PAGE_GAP
        for idx in range(len(self.pages)):
            rc = self._rects_canvas.get(idx, {})
            if rc.get("parafe"):
                self._draw_rect(*rc["parafe"], self.COLOR_PARAFE, self.OUTLINE_P)
            if rc.get("sig"):
                self._draw_rect(*rc["sig"], self.COLOR_SIG, self.OUTLINE_S)
        if self._live_coords:
            c = self.COLOR_PARAFE if self.mode == "parafe" else self.COLOR_SIG
            o = self.OUTLINE_P    if self.mode == "parafe" else self.OUTLINE_S
            self._draw_rect(*self._live_coords, c, o)

    def _draw_rect(self, cx1, cy1, cx2, cy2, fill_color, outline_color):
        x, y = min(cx1, cx2), min(cy1, cy2)
        w, h = abs(cx2 - cx1), abs(cy2 - cy1)
        with self.canvas:
            Color(*fill_color)
            Rectangle(pos=(x, y), size=(w, h))
            Color(*outline_color)
            Line(rectangle=(x, y, w, h), width=2)

    def _page_at(self, cx, cy):
        for idx, (x_off, y_off, dw, dh, scale) in enumerate(self._page_geom):
            if x_off <= cx <= x_off + dw and y_off <= cy <= y_off + dh:
                return idx, scale, x_off, y_off, dh
        return None, None, None, None, None

    def _canvas_to_real(self, cx, cy, x_off, y_off, dh, scale):
        px         = (cx - x_off) / scale
        py_preview = (cy - y_off) / scale
        py_pdf     = (dh / scale) - py_preview
        return int(px * self.dpi_ratio), int(py_pdf * self.dpi_ratio)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.mode:
            return False
        idx, scale, x_off, y_off, dh = self._page_at(*touch.pos)
        if idx is None:
            return False
        touch.grab(self)
        self._drag_start    = touch.pos
        self._drag_page_idx = idx
        self._drag_geom     = (scale, x_off, y_off, dh)
        self._live_coords   = None
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or not self._drag_start:
            return False
        self._live_coords = (*self._drag_start, *touch.pos)
        self._redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self or not self._drag_start:
            return False
        touch.ungrab(self)
        x0, y0 = self._drag_start
        x1, y1 = touch.pos
        self._drag_start  = None
        self._live_coords = None
        idx               = self._drag_page_idx
        scale, x_off, y_off, dh = self._drag_geom

        if abs(x1 - x0) < 12 or abs(y1 - y0) < 12:
            self._redraw()
            return True

        rx0, ry0 = self._canvas_to_real(min(x0,x1), max(y0,y1), x_off, y_off, dh, scale)
        rx1, ry1 = self._canvas_to_real(max(x0,x1), min(y0,y1), x_off, y_off, dh, scale)
        rect         = Rect(rx0, ry0, rx1, ry1)
        canvas_coords = (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))

        if self.mode == "parafe":
            self._rects[idx]["parafe"]        = rect
            self._rects_canvas[idx]["parafe"] = canvas_coords
        else:
            self._rects[idx]["sig"]        = rect
            self._rects_canvas[idx]["sig"] = canvas_coords
        self._redraw()
        return True

    def get_rect(self, mode):
        for idx in reversed(range(len(self.pages))):
            r = self._rects.get(idx, {}).get(mode)
            if r:
                return r
        return None

    def clear_rects(self):
        for idx in range(len(self.pages)):
            self._rects[idx]        = {"parafe": None, "sig": None}
            self._rects_canvas[idx] = {"parafe": None, "sig": None}
        self._redraw()

    def restore_rects(self, parafe_rect, sig_rect):
        if parafe_rect and self.pages:
            self._rects[0]["parafe"] = parafe_rect
        if sig_rect and self.pages:
            self._rects[0]["sig"] = sig_rect


# -------------------------------------------------------------------------
# ECRAN PICKER
# -------------------------------------------------------------------------

class PickerScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", spacing=0)

        bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=H_BTN,
                        spacing=4, padding=(4, 4))
        with bar.canvas.before:
            Color(*C_HEADER)
            self._bar_bg = Rectangle()
        bar.bind(size=lambda w, v: setattr(self._bar_bg, "size", v),
                 pos =lambda w, v: setattr(self._bar_bg, "pos",  v))

        self.btn_parafe = make_btn("Parafe",    bg=(0.49, 0.11, 0.64, 1), fg=C_WHITE,
                                   on_press=lambda _: self._set_mode("parafe"))
        self.btn_sig    = make_btn("Signature", bg=(0.18, 0.63, 0.28, 1), fg=C_WHITE,
                                   on_press=lambda _: self._set_mode("sig"))
        btn_clear = make_btn("Effacer", bg=C_RED,   fg=C_WHITE, size_hint_x=0.35,
                             on_press=lambda _: self._clear())
        btn_ok    = make_btn("OK",      bg=C_GREEN, fg=C_WHITE, size_hint_x=0.25,
                             on_press=lambda _: self._validate())
        for w in (self.btn_parafe, self.btn_sig, btn_clear, btn_ok):
            bar.add_widget(w)
        root.add_widget(bar)

        self.status_lbl = make_label(
            "Choisir un mode, puis glisser pour delimiter la zone",
            color=(0.3, 0.3, 0.3, 1), height=H_LABEL, halign="center"
        )
        root.add_widget(self.status_lbl)

        self.scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
            do_scroll_y=True,
            scroll_type=["bars", "content"],
        )
        self.picker = PickerCanvas(size_hint=(1, None))
        self.scroll.add_widget(self.picker)
        root.add_widget(self.scroll)
        self.add_widget(root)

    def _set_mode(self, mode):
        self.picker.mode = mode
        self.status_lbl.text = (
            "Mode PARAFE - glisser sur la page souhaitee"
            if mode == "parafe" else
            "Mode SIGNATURE - glisser sur la page souhaitee"
        )

    def _clear(self):
        self.picker.clear_rects()
        self.picker.mode = None
        self.status_lbl.text = "Zones effacees. Choisir un mode."

    def _validate(self):
        app = App.get_running_app()
        app.parafe_rect = self.picker.get_rect("parafe")
        app.sig_rect    = self.picker.get_rect("sig")
        app.sm.transition = SlideTransition(direction="right")
        app.sm.current = "main"
        app.main_screen.refresh_zones_label()

    def load_pdf_preview(self, pdf_path):
        """Charge toutes les pages en thread pour ne pas bloquer l'UI."""
        self.status_lbl.text = "Chargement des pages..."
        self.picker.pages = []
        self.picker.canvas.clear()

        def _load():
            try:
                pages = pdf_preview_all_pages(pdf_path, dpi=DPI_PREVIEW)
                def _done(dt):
                    self.picker.set_pages(pages)
                    app = App.get_running_app()
                    self.picker.restore_rects(app.parafe_rect, app.sig_rect)
                    n = len(pages)
                    self.status_lbl.text = "{} page{} - choisir un mode puis glisser".format(
                        n, "s" if n > 1 else "")
                Clock.schedule_once(_done)
            except Exception as exc:
                Clock.schedule_once(
                    lambda dt, e=str(exc): setattr(
                        self.status_lbl, "text", "Erreur : " + e))

        threading.Thread(target=_load, daemon=True).start()


# -------------------------------------------------------------------------
# SELECTEUR DE FICHIER NATIF ANDROID
# -------------------------------------------------------------------------

_file_picker_callback = None
_file_picker_is_pdf   = False

if ANDROID:
    from android.activity import bind as activity_bind  # type: ignore

    def _on_activity_result(requestCode, resultCode, intent):
        global _file_picker_callback, _file_picker_is_pdf
        RESULT_OK = -1
        if requestCode == 42 and resultCode == RESULT_OK and intent and _file_picker_callback:
            uri    = intent.getData()
            cb     = _file_picker_callback
            is_pdf = _file_picker_is_pdf
            _file_picker_callback = None
            _file_picker_is_pdf   = False
            try:
                ContentResolver  = autoclass("android.content.ContentResolver")
                PythonActivity   = autoclass("org.kivy.android.PythonActivity")
                context          = PythonActivity.mActivity
                resolver         = context.getContentResolver()
                cursor = resolver.query(uri, None, None, None, None)
                path   = None
                real_name = None
                display_name = None
                if cursor and cursor.moveToFirst():
                    try:
                        idx = cursor.getColumnIndex("_data")
                        if idx >= 0:
                            path = cursor.getString(idx)
                    except Exception:
                        pass
                    try:
                        idx2 = cursor.getColumnIndex("_display_name")
                        if idx2 >= 0:
                            real_name = cursor.getString(idx2)
                    except Exception:
                        pass
                    cursor.close()
                if not path:
                    import tempfile
                    istream = resolver.openInputStream(uri)
                    suffix  = ".pdf" if is_pdf else ".png"
                    try:
                        name = real_name or uri.getLastPathSegment()
                        if name and "." in name:
                            suffix = "." + name.rsplit(".", 1)[-1]
                    except Exception:
                        pass
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    buf = bytearray(65536)
                    while True:
                        n = istream.read(buf)
                        if n < 0:
                            break
                        tmp.write(bytes(buf[:n]))
                    tmp.close()
                    istream.close()
                    path = tmp.name
                if is_pdf:
                    try:
                        display_name = real_name or uri.getLastPathSegment()
                    except Exception:
                        pass
                    if not display_name and path:
                        display_name = os.path.basename(path)
                    if display_name:
                        App.get_running_app().pdf_display_name = display_name
                if path:
                    Clock.schedule_once(lambda dt: cb(path))
            except Exception:
                import traceback
                traceback.print_exc()

    activity_bind(on_activity_result=_on_activity_result)


def open_file_picker(callback, mime_type="*/*"):
    global _file_picker_callback, _file_picker_is_pdf
    if ANDROID and HAS_JNIUS:
        _file_picker_callback = callback
        _file_picker_is_pdf   = (mime_type == "application/pdf")
        Intent         = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType(mime_type)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        PythonActivity.mActivity.startActivityForResult(intent, 42)
    else:
        filters = ["*.pdf"] if mime_type == "application/pdf" else ["*.png", "*.jpg", "*.jpeg"]
        FilePopup(callback, filters=filters).open()


# -------------------------------------------------------------------------
# WIDGET : FILE CHOOSER POPUP (desktop uniquement)
# -------------------------------------------------------------------------

class FilePopup(Popup):

    def __init__(self, callback, filters=None, **kwargs):
        super().__init__(**kwargs)
        self.callback  = callback
        self.title     = "Choisir un fichier"
        self.size_hint = (0.95, 0.85)
        layout = BoxLayout(orientation="vertical", spacing=8, padding=8)
        self.chooser = FileChooserListView(
            path=self._get_start_path(),
            filters=filters or ["*"],
            size_hint_y=1,
        )
        layout.add_widget(self.chooser)
        btn_row = BoxLayout(size_hint_y=None, height=H_BTN, spacing=8)
        btn_row.add_widget(make_btn("Annuler",      bg=C_RED,   fg=C_WHITE,
                                    on_press=lambda _: self.dismiss()))
        btn_row.add_widget(make_btn("Selectionner", bg=C_GREEN, fg=C_WHITE,
                                    on_press=self._select))
        layout.add_widget(btn_row)
        self.content = layout

    @staticmethod
    def _get_start_path():
        for p in ("/sdcard", "/storage/emulated/0", os.path.expanduser("~")):
            if os.path.isdir(p):
                return p
        return "/"

    def _select(self, *_):
        sel = self.chooser.selection
        if sel:
            self.dismiss()
            self.callback(sel[0])


# -------------------------------------------------------------------------
# SLIDER NOMME
# -------------------------------------------------------------------------

class NamedSlider(BoxLayout):

    def __init__(self, label, lo, hi, value, step=0.05, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=H_SLIDER, spacing=6, **kwargs)
        self._lbl = make_label(label, height=H_SLIDER, halign="left")
        self._lbl.size_hint_x = 0.38
        self.slider = Slider(min=lo, max=hi, value=value, step=step, size_hint_x=0.44)
        self._val_lbl = make_label("{:.2f}".format(value), height=H_SLIDER, halign="right")
        self._val_lbl.size_hint_x = 0.18
        self.slider.bind(value=self._on_value)
        self.add_widget(self._lbl)
        self.add_widget(self.slider)
        self.add_widget(self._val_lbl)

    def _on_value(self, inst, v):
        self._val_lbl.text = "{:.2f}".format(v)

    @property
    def value(self):
        return self.slider.value


# -------------------------------------------------------------------------
# ECRAN PRINCIPAL
# -------------------------------------------------------------------------

class MainScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_ui()

    def _build_ui(self):
        outer = BoxLayout(orientation="vertical")
        with outer.canvas.before:
            Color(*C_BG)
            self._bg = Rectangle()
        outer.bind(size=lambda w, v: setattr(self._bg, "size", v),
                   pos =lambda w, v: setattr(self._bg, "pos",  v))

        header = BoxLayout(size_hint_y=None, height=H_HEADER, padding=(12, 8))
        with header.canvas.before:
            Color(*C_HEADER)
            self._hbg = Rectangle()
        header.bind(size=lambda w, v: setattr(self._hbg, "size", v),
                    pos =lambda w, v: setattr(self._hbg, "pos",  v))
        header.add_widget(Label(text="[b]Fake Scan PDF[/b]", markup=True,
                                color=C_WHITE, font_size=FS_SECTION, halign="left"))
        outer.add_widget(header)

        scroll  = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        content = BoxLayout(orientation="vertical", spacing=10,
                            padding=(12, 10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        content.add_widget(section_label("Fichiers"))

        row_pdf = BoxLayout(size_hint_y=None, height=H_BTN, spacing=6)
        row_pdf.add_widget(make_btn("PDF", bg=(0.88, 0.96, 1, 1), size_hint_x=0.38,
                                    on_press=lambda _: self._pick_pdf()))
        self.pdf_label = make_label("Aucun PDF", color=(0.5, 0.5, 0.5, 1), height=H_BTN)
        row_pdf.add_widget(self.pdf_label)
        content.add_widget(row_pdf)

        self.btn_picker = make_btn("Definir les zones (parafe / signature)",
                                   bg=C_ORANGE, fg=C_WHITE, height=H_BTN,
                                   on_press=lambda _: self._open_picker())
        self.btn_picker.disabled = True
        content.add_widget(self.btn_picker)

        self.zones_label = make_label("Zones : non definies",
                                      color=(0.55, 0.35, 0.65, 1), height=H_LABEL, italic=True)
        content.add_widget(self.zones_label)

        row_p = BoxLayout(size_hint_y=None, height=H_BTN, spacing=6)
        row_p.add_widget(make_btn("Parafe", bg=(0.96, 0.90, 1.00, 1), size_hint_x=0.38,
                                   on_press=lambda _: self._pick_parafe()))
        self.parafe_label = make_label("Aucune image", color=(0.5, 0.5, 0.5, 1), height=H_BTN)
        row_p.add_widget(self.parafe_label)
        content.add_widget(row_p)

        row_s = BoxLayout(size_hint_y=None, height=H_BTN, spacing=6)
        row_s.add_widget(make_btn("Signature", bg=(0.90, 0.97, 0.90, 1), size_hint_x=0.38,
                                   on_press=lambda _: self._pick_sig()))
        self.sig_label = make_label("Aucune image", color=(0.5, 0.5, 0.5, 1), height=H_BTN)
        row_s.add_widget(self.sig_label)
        content.add_widget(row_s)

        content.add_widget(section_label("Pages  (ex : 1  ou  1,3-5,7)"))

        row_pp = BoxLayout(size_hint_y=None, height=H_INPUT, spacing=6)
        row_pp.add_widget(make_label("Parafe :", height=H_INPUT, halign="left"))
        self.parafe_pages = TextInput(text="1", multiline=False,
                                      size_hint_y=None, height=H_INPUT, font_size=FS_INPUT)
        row_pp.add_widget(self.parafe_pages)
        content.add_widget(row_pp)

        row_sp = BoxLayout(size_hint_y=None, height=H_INPUT, spacing=6)
        row_sp.add_widget(make_label("Signature :", height=H_INPUT, halign="left"))
        self.sig_pages = TextInput(text="1", multiline=False,
                                   size_hint_y=None, height=H_INPUT, font_size=FS_INPUT)
        row_sp.add_widget(self.sig_pages)
        content.add_widget(row_sp)

        content.add_widget(section_label("Effets scan"))

        from kivy.uix.togglebutton import ToggleButton
        toggle_row = BoxLayout(size_hint_y=None, height=H_BTN, spacing=dp(6))
        self.btn_nb  = ToggleButton(
            text="Noir & Blanc", group="colormode", state="down",
            background_normal="", background_down="",
            background_color=C_HEADER, color=C_WHITE,
            font_size=FS_BTN, size_hint=(0.5, None), height=H_BTN,
        )
        self.btn_col = ToggleButton(
            text="Couleurs", group="colormode", state="normal",
            background_normal="", background_down="",
            background_color=C_GREY_BTN, color=C_TEXT_DARK,
            font_size=FS_BTN, size_hint=(0.5, None), height=H_BTN,
        )
        def _on_toggle(btn, *_):
            if btn.state == "down":
                self.btn_nb.background_color  = C_HEADER if self.btn_nb.state  == "down" else C_GREY_BTN
                self.btn_col.background_color = C_HEADER if self.btn_col.state == "down" else C_GREY_BTN
                self.btn_nb.color  = C_WHITE     if self.btn_nb.state  == "down" else C_TEXT_DARK
                self.btn_col.color = C_WHITE     if self.btn_col.state == "down" else C_TEXT_DARK
        self.btn_nb.bind(state=_on_toggle)
        self.btn_col.bind(state=_on_toggle)
        toggle_row.add_widget(self.btn_nb)
        toggle_row.add_widget(self.btn_col)
        content.add_widget(toggle_row)

        self.sl_tilt       = NamedSlider("Tilt (deg)",  0.0, 3.0, 1.2, 0.1)
        self.sl_blur       = NamedSlider("Flou",        0.0, 2.0, 0.3, 0.05)
        self.sl_contrast   = NamedSlider("Contraste",   0.7, 1.6, 1.1, 0.05)
        self.sl_brightness = NamedSlider("Luminosite",  0.7, 1.3, 1.0, 0.05)
        for w in (self.sl_tilt, self.sl_blur, self.sl_contrast, self.sl_brightness):
            content.add_widget(w)

        self.btn_gen = make_btn("GENERER PDF SCAN", bg=C_GREEN, fg=C_WHITE,
                                height=H_BTN_GEN, bold=True, on_press=lambda _: self._run())
        content.add_widget(self.btn_gen)

        self.progress_lbl = make_label("", color=(0.4, 0.4, 0.4, 1),
                                       height=H_LABEL, halign="center", italic=True)
        content.add_widget(self.progress_lbl)
        content.add_widget(Widget(size_hint_y=None, height=H_SPACER))

        scroll.add_widget(content)
        outer.add_widget(scroll)
        self.add_widget(outer)

    def _pick_pdf(self):
        App.get_running_app().pdf_display_name = None
        open_file_picker(self._on_pdf_selected, mime_type="application/pdf")

    def _on_pdf_selected(self, path):
        app = App.get_running_app()
        app.pdf_path    = path
        app.parafe_rect = None
        app.sig_rect    = None
        if not app.pdf_display_name:
            app.pdf_display_name = os.path.basename(path)
        self.pdf_label.text  = app.pdf_display_name
        self.pdf_label.color = (0.10, 0.14, 0.55, 1)
        self.btn_picker.disabled = False
        try:
            app.total_pages = pdf_page_count(path)
        except Exception:
            app.total_pages = 999
        self.refresh_zones_label()

    def _pick_parafe(self):
        open_file_picker(self._on_parafe_selected, mime_type="image/*")

    def _on_parafe_selected(self, path):
        App.get_running_app().parafe_path = path
        self.parafe_label.text  = os.path.basename(path)
        self.parafe_label.color = (0.30, 0.05, 0.40, 1)

    def _pick_sig(self):
        open_file_picker(self._on_sig_selected, mime_type="image/*")

    def _on_sig_selected(self, path):
        App.get_running_app().sig_path = path
        self.sig_label.text  = os.path.basename(path)
        self.sig_label.color = (0.05, 0.35, 0.05, 1)

    def _open_picker(self):
        app = App.get_running_app()
        if not app.pdf_path:
            self._toast("Charge d'abord un PDF")
            return
        app.sm.transition = SlideTransition(direction="left")
        app.sm.current    = "picker"
        app.picker_screen.load_pdf_preview(app.pdf_path)

    def refresh_zones_label(self):
        app   = App.get_running_app()
        parts = []
        if app.parafe_rect:
            r = app.parafe_rect
            parts.append("Parafe {}x{}px".format(r.w, r.h))
        else:
            parts.append("Parafe : non defini")
        if app.sig_rect:
            r = app.sig_rect
            parts.append("Sig {}x{}px".format(r.w, r.h))
        else:
            parts.append("Sig : non defini")
        self.zones_label.text = "  |  ".join(parts)

    def _run(self):
        app = App.get_running_app()
        if not app.pdf_path:
            self._toast("Selectione un PDF"); return
        if not app.parafe_path and not app.sig_path:
            self._toast("Selectione au moins une image"); return
        if app.parafe_path and not app.parafe_rect:
            self._toast("Definis la zone du parafe"); return
        if app.sig_path and not app.sig_rect:
            self._toast("Definis la zone de la signature"); return

        self.btn_gen.disabled = True
        self.btn_gen.text     = "Traitement..."
        self._prog("Demarrage...")

        params = {
            "pdf_path":     app.pdf_path,
            "pdf_name":     getattr(app, "pdf_display_name", None) or os.path.basename(app.pdf_path),
            "parafe_path":  app.parafe_path,
            "sig_path":     app.sig_path,
            "parafe_rect":  app.parafe_rect,
            "sig_rect":     app.sig_rect,
            "parafe_pages": parse_pages(self.parafe_pages.text, app.total_pages),
            "sig_pages":    parse_pages(self.sig_pages.text,    app.total_pages),
            "tilt":         self.sl_tilt.value,
            "blur":         self.sl_blur.value,
            "contrast":     self.sl_contrast.value,
            "brightness":   self.sl_brightness.value,
            "grayscale":    self.btn_nb.state == "down",
        }
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, p):
        try:
            Clock.schedule_once(lambda dt: self._prog("Conversion du PDF..."))
            images = pdf_to_pil_list(p["pdf_path"], dpi=DPI_PROCESS)
            total  = len(images)

            parafe_base = Image.open(p["parafe_path"]).convert("RGBA") if p["parafe_path"] else None
            sig_base    = Image.open(p["sig_path"]).convert("RGBA")    if p["sig_path"]    else None

            out_images = []
            for idx, page_img in enumerate(images):
                page_num = idx + 1
                Clock.schedule_once(
                    lambda dt, n=page_num, t=total: self._prog("Page {}/{}...".format(n, t))
                )
                page_img = ensure_white_bg(page_img)
                page_img = page_img.convert("RGBA")

                if parafe_base and page_num in p["parafe_pages"] and p["parafe_rect"]:
                    varied         = vary_signature(parafe_base)
                    fitted, px, py = fit_into_rect(varied, p["parafe_rect"], jitter=True)
                    page_img.paste(fitted, (px, py), fitted)

                if sig_base and page_num in p["sig_pages"] and p["sig_rect"]:
                    varied         = vary_signature(sig_base)
                    fitted, sx, sy = fit_into_rect(varied, p["sig_rect"], jitter=False)
                    page_img.paste(fitted, (sx, sy), fitted)

                page_img = simulate_scan(
                    page_img,
                    tilt=p["tilt"], blur=p["blur"],
                    contrast=p["contrast"], brightness=p["brightness"],
                    grayscale=p["grayscale"],
                )
                out_images.append(page_img.convert("RGB"))

            out_filename = os.path.splitext(p["pdf_name"])[0] + "_scan.pdf"
            Clock.schedule_once(lambda dt: self._prog("Encodage PDF..."))

            if ANDROID and HAS_JNIUS:
                try:
                    ContentValues  = autoclass("android.content.ContentValues")
                    Downloads      = autoclass("android.provider.MediaStore$Downloads")
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    context        = PythonActivity.mActivity
                    resolver       = context.getContentResolver()
                    values = ContentValues()
                    values.put("_display_name", out_filename)
                    values.put("mime_type",     "application/pdf")
                    values.put("relative_path", "Download/")
                    try:
                        resolver.delete(
                            Downloads.EXTERNAL_CONTENT_URI,
                            "_display_name=?", [out_filename])
                    except Exception:
                        pass
                    item_uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
                    ostream  = resolver.openOutputStream(item_uri)
                    buf      = io.BytesIO()
                    pil_list_to_pdf(out_images, buf)
                    ostream.write(buf.getvalue())
                    ostream.close()
                    content_uri_str = item_uri.toString()
                    Clock.schedule_once(
                        lambda dt, n=out_filename, u=content_uri_str: self._on_done(n, u))
                except Exception:
                    import traceback; traceback.print_exc()
                    Environment = autoclass("android.os.Environment")
                    out_dir  = Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
                    out_path = os.path.join(out_dir, out_filename)
                    pil_list_to_pdf(out_images, out_path)
                    Clock.schedule_once(
                        lambda dt, n=out_filename, u=None: self._on_done(n, u))
            else:
                out_path = os.path.join(os.path.dirname(p["pdf_path"]), out_filename)
                pil_list_to_pdf(out_images, out_path)
                Clock.schedule_once(
                    lambda dt, n=out_filename, u=None: self._on_done(n, u))

        except Exception as exc:
            import traceback
            err = traceback.format_exc()
            Clock.schedule_once(lambda dt, e=err: self._on_error(e))

    def _on_done(self, out_filename, content_uri_str=None):
        self._reset_btn()
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        content.add_widget(Label(
            text="PDF genere :\n" + out_filename,
            font_size=FS_POPUP, halign="center",
            text_size=(Window.width * 0.78, None),
            size_hint_y=None, height=dp(72),
        ))
        btn_row = BoxLayout(size_hint_y=None, height=H_BTN, spacing=dp(8))
        popup   = Popup(title="Termine", content=content,
                        size_hint=(0.88, None), height=dp(210))

        def _open_pdf(_):
            popup.dismiss()
            if ANDROID and HAS_JNIUS and content_uri_str:
                try:
                    Intent         = autoclass("android.content.Intent")
                    Uri            = autoclass("android.net.Uri")
                    JavaString     = autoclass("java.lang.String")
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    ctx    = PythonActivity.mActivity
                    uri    = Uri.parse(content_uri_str)
                    intent = Intent(Intent.ACTION_VIEW)
                    intent.setDataAndType(uri, "application/pdf")
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    ctx.startActivity(Intent.createChooser(intent, JavaString("Ouvrir avec")))
                except Exception as exc:
                    self._toast("Erreur : " + str(exc), duration=4)
            else:
                self._toast("Fichier : Telechargements/" + out_filename, duration=5)

        btn_row.add_widget(make_btn("Ouvrir", bg=C_GREEN,    fg=C_WHITE, on_press=_open_pdf))
        btn_row.add_widget(make_btn("Fermer", bg=C_GREY_BTN, fg=C_TEXT_DARK,
                                    on_press=lambda _: popup.dismiss()))
        content.add_widget(btn_row)
        popup.open()

    def _on_error(self, err):
        self._reset_btn()
        Popup(title="Erreur",
              content=Label(text=err, font_size=FS_POPUP,
                            text_size=(Window.width * 0.85, None)),
              size_hint=(0.9, 0.7)).open()

    def _reset_btn(self):
        self.btn_gen.disabled = False
        self.btn_gen.text     = "GENERER PDF SCAN"
        self._prog("")

    def _prog(self, msg):
        self.progress_lbl.text = msg

    def _toast(self, msg, duration=2.5):
        pop = Popup(
            title="",
            content=Label(text=msg, halign="center", font_size=FS_POPUP),
            size_hint=(0.8, None), height=H_BTN * 2,
            auto_dismiss=True, separator_height=0,
        )
        pop.open()
        Clock.schedule_once(lambda dt: pop.dismiss(), duration)


# -------------------------------------------------------------------------
# APPLICATION
# -------------------------------------------------------------------------

class FakeScanApp(App):

    def build(self):
        self.pdf_path         = None
        self.pdf_display_name = None
        self.parafe_path      = None
        self.sig_path         = None
        self.total_pages      = 999
        self.parafe_rect      = None
        self.sig_rect         = None

        if ANDROID and not HAS_JNIUS:
            return Label(text="[b]Erreur :[/b]\nJnius non disponible.",
                         markup=True, halign="center", font_size=FS_POPUP)
        if not ANDROID and not HAS_FITZ:
            return Label(text="[b]Erreur :[/b]\nPyMuPDF non installe.\n\npip install pymupdf",
                         markup=True, halign="center", font_size=FS_POPUP)

        self.sm = ScreenManager()
        self.main_screen   = MainScreen(name="main")
        self.picker_screen = PickerScreen(name="picker")
        self.sm.add_widget(self.main_screen)
        self.sm.add_widget(self.picker_screen)
        return self.sm


if __name__ == "__main__":
    FakeScanApp().run()
