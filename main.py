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

def _pil_grain_L(img, strength=4):
    """Bruit grain sur image en niveaux de gris (mode L) - PIL pur, sans numpy."""
    w, h = img.size
    noise = Image.frombytes('L', (w, h), os.urandom(w * h))
    noise = noise.point(lambda x: int(x / 255 * (2 * strength)) - strength + 128)
    return ImageChops.add(img, noise, scale=1, offset=-128)


def _pil_grain_RGBA(img, strength=8):
    """Bruit grain sur image RGBA - PIL pur, sans numpy."""
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

# Polices (sp : respecte la preference utilisateur de taille de texte)
FS_BTN     = "16sp"   # boutons
FS_LABEL   = "15sp"   # labels courants
FS_SECTION = "17sp"   # titres de section
FS_INPUT   = "16sp"   # champs de saisie
FS_HEADER  = "20sp"   # titre app
FS_POPUP   = "15sp"   # toasts / popups

# Hauteurs (dp : independant de la densite, equivalent aux dp Android natifs)
H_BTN      = dp(48)   # touch target minimum recommande par Material Design
H_LABEL    = dp(36)
H_SECTION  = dp(40)
H_INPUT    = dp(48)
H_HEADER   = dp(56)   # toolbar Android standard
H_BTN_GEN  = dp(56)   # bouton principal
H_SLIDER   = dp(48)
H_SPACER   = dp(16)


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
        # Grain couleur : appliqué sur chaque canal RGB
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


def _android_pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW):
    File                 = autoclass("java.io.File")
    ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")
    PdfRenderer          = autoclass("android.graphics.pdf.PdfRenderer")
    PdfRendererPage      = autoclass("android.graphics.pdf.PdfRenderer$Page")
    Bitmap               = autoclass("android.graphics.Bitmap")
    BitmapConfig         = autoclass("android.graphics.Bitmap$Config")
    BitmapCompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
    ByteArrayOS          = autoclass("java.io.ByteArrayOutputStream")

    pfd      = ParcelFileDescriptor.open(File(pdf_path), ParcelFileDescriptor.MODE_READ_ONLY)
    renderer = PdfRenderer(pfd)
    page     = renderer.openPage(page_index)
    scale    = dpi / 72.0
    width    = int(page.getWidth()  * scale)
    height   = int(page.getHeight() * scale)
    bitmap   = Bitmap.createBitmap(width, height, BitmapConfig.ARGB_8888)
    page.render(bitmap, None, None, PdfRendererPage.RENDER_MODE_FOR_DISPLAY)
    page.close()
    renderer.close()
    pfd.close()
    baos = ByteArrayOS()
    bitmap.compress(BitmapCompressFormat.PNG, 100, baos)
    return Image.open(io.BytesIO(bytes(baos.toByteArray())))


def _android_pdf_page_count(pdf_path):
    File                 = autoclass("java.io.File")
    ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")
    PdfRenderer          = autoclass("android.graphics.pdf.PdfRenderer")
    pfd      = ParcelFileDescriptor.open(File(pdf_path), ParcelFileDescriptor.MODE_READ_ONLY)
    renderer = PdfRenderer(pfd)
    count    = renderer.getPageCount()
    renderer.close()
    pfd.close()
    return count


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
    if ANDROID and HAS_JNIUS:
        count = _android_pdf_page_count(pdf_path)
        return [_android_pdf_page_to_pil(pdf_path, i, dpi) for i in range(count)]
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


def pil_list_to_pdf(images, out_path):
    if not images:
        return
    rgb = [img.convert("RGB") for img in images]
    rgb[0].save(out_path, save_all=True, append_images=rgb[1:], resolution=DPI_PROCESS)


def pil_to_kivy_texture(pil_img):
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data    = pil_img.tobytes()
    texture = Texture.create(size=(pil_img.width, pil_img.height), colorfmt="rgba")
    texture.blit_buffer(data, colorfmt="rgba", bufferfmt="ubyte")
    texture.flip_vertical()
    return texture


# -------------------------------------------------------------------------
# WIDGET : ZONE DE DESSIN RECTANGLES (PickerCanvas)
# -------------------------------------------------------------------------

class PickerCanvas(Widget):

    COLOR_PARAFE = (0.62, 0.14, 0.80, 0.45)
    COLOR_SIG    = (0.18, 0.63, 0.18, 0.45)
    OUTLINE_P    = (0.62, 0.14, 0.80, 1.0)
    OUTLINE_S    = (0.18, 0.63, 0.18, 1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode          = None
        self.preview_pil   = None
        self.preview_w     = 1
        self.preview_h     = 1
        self.scale_factor  = 1.0
        self.dpi_ratio     = DPI_PROCESS / DPI_PREVIEW
        self._rect_parafe_canvas = None
        self._rect_sig_canvas    = None
        self.rect_parafe = None
        self.rect_sig    = None
        self._drag_start  = None
        self._live_coords = None
        self._offset_x    = 0
        self._offset_y    = 0
        self.bind(size=self._redraw, pos=self._redraw)

    def set_preview(self, pil_img):
        self.preview_pil = pil_img
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        if not self.preview_pil:
            return
        sw = self.width  / self.preview_pil.width
        sh = self.height / self.preview_pil.height
        self.scale_factor = min(sw, sh)
        dw = int(self.preview_pil.width  * self.scale_factor)
        dh = int(self.preview_pil.height * self.scale_factor)
        self._offset_x = (self.width  - dw) / 2 + self.x
        self._offset_y = (self.height - dh) / 2 + self.y
        self.preview_w = dw
        self.preview_h = dh
        tex = pil_to_kivy_texture(self.preview_pil)
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, pos=(self._offset_x, self._offset_y), size=(dw, dh))
        if self._rect_parafe_canvas:
            self._draw_rect_canvas(*self._rect_parafe_canvas, self.COLOR_PARAFE, self.OUTLINE_P)
        if self._rect_sig_canvas:
            self._draw_rect_canvas(*self._rect_sig_canvas, self.COLOR_SIG, self.OUTLINE_S)
        if self._live_coords:
            c = self.COLOR_PARAFE if self.mode == "parafe" else self.COLOR_SIG
            o = self.OUTLINE_P    if self.mode == "parafe" else self.OUTLINE_S
            self._draw_rect_canvas(*self._live_coords, c, o)

    def _draw_rect_canvas(self, cx1, cy1, cx2, cy2, fill_color, outline_color):
        x, y = min(cx1, cx2), min(cy1, cy2)
        w, h = abs(cx2 - cx1), abs(cy2 - cy1)
        with self.canvas:
            Color(*fill_color)
            Rectangle(pos=(x, y), size=(w, h))
            Color(*outline_color)
            Line(rectangle=(x, y, w, h), width=2)

    def _canvas_to_preview(self, cx, cy):
        px = (cx - self._offset_x) / self.scale_factor
        py = (cy - self._offset_y) / self.scale_factor
        return px, py

    def _canvas_to_real(self, cx, cy):
        px, py = self._canvas_to_preview(cx, cy)
        return int(px * self.dpi_ratio), int(py * self.dpi_ratio)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.mode:
            return False
        touch.grab(self)
        self._drag_start  = touch.pos
        self._live_coords = None
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
        if abs(x1 - x0) < 12 or abs(y1 - y0) < 12:
            self._redraw()
            return True
        rx0, ry0 = self._canvas_to_real(min(x0, x1), min(y0, y1))
        rx1, ry1 = self._canvas_to_real(max(x0, x1), max(y0, y1))
        if self.preview_pil:
            real_h = int(self.preview_pil.height * self.dpi_ratio)
            ry0_f  = real_h - ry1
            ry1_f  = real_h - ry0
        else:
            ry0_f, ry1_f = ry0, ry1
        rect = Rect(rx0, ry0_f, rx1, ry1_f)
        if self.mode == "parafe":
            self.rect_parafe         = rect
            self._rect_parafe_canvas = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        else:
            self.rect_sig            = rect
            self._rect_sig_canvas    = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self._redraw()
        return True

    def clear_rects(self):
        self._rect_parafe_canvas = None
        self._rect_sig_canvas    = None
        self.rect_parafe         = None
        self.rect_sig            = None
        self._redraw()


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

        self.picker = PickerCanvas()
        root.add_widget(self.picker)
        self.add_widget(root)

    def _set_mode(self, mode):
        self.picker.mode = mode
        if mode == "parafe":
            self.status_lbl.text = "Mode PARAFE actif — glisser pour delimiter"
        else:
            self.status_lbl.text = "Mode SIGNATURE actif — glisser pour delimiter"

    def _clear(self):
        self.picker.clear_rects()
        self.picker.mode = None
        self.status_lbl.text = "Zones effacees. Choisir un mode."

    def _validate(self):
        app = App.get_running_app()
        app.parafe_rect = self.picker.rect_parafe
        app.sig_rect    = self.picker.rect_sig
        app.sm.transition = SlideTransition(direction="right")
        app.sm.current = "main"
        app.main_screen.refresh_zones_label()

    def load_pdf_preview(self, pdf_path):
        try:
            img = pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW)
            self.picker.set_preview(img)
            app = App.get_running_app()
            self.picker.rect_parafe = app.parafe_rect
            self.picker.rect_sig    = app.sig_rect
        except Exception as exc:
            self.status_lbl.text = "Erreur apercu : " + str(exc)


# -------------------------------------------------------------------------
# SELECTEUR DE FICHIER NATIF ANDROID
# -------------------------------------------------------------------------

# Callback global pour recevoir le résultat de l'Intent
_file_picker_callback = None

if ANDROID:
    from android.activity import bind as activity_bind  # type: ignore

    def _on_activity_result(requestCode, resultCode, intent):
        global _file_picker_callback
        RESULT_OK = -1
        if requestCode == 42 and resultCode == RESULT_OK and intent and _file_picker_callback:
            uri  = intent.getData()
            cb   = _file_picker_callback
            _file_picker_callback = None

            # Résoudre l'URI en chemin réel
            try:
                ContentResolver  = autoclass("android.content.ContentResolver")
                PythonActivity   = autoclass("org.kivy.android.PythonActivity")
                context          = PythonActivity.mActivity
                resolver         = context.getContentResolver()

                # Essayer d'obtenir le chemin via cursor
                cursor = resolver.query(uri, None, None, None, None)
                path   = None
                real_name = None
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

                # Si pas de chemin direct, copier vers cache
                if not path:
                    import tempfile
                    istream = resolver.openInputStream(uri)
                    suffix  = ".pdf"
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
                    if real_name:
                        App.get_running_app().pdf_display_name = real_name

                if path:
                    # Stocker le vrai nom pour le fichier de sortie
                    if real_name:
                        App.get_running_app().pdf_display_name = real_name
                    Clock.schedule_once(lambda dt: cb(path))
            except Exception as exc:
                import traceback
                traceback.print_exc()

    activity_bind(on_activity_result=_on_activity_result)


def open_file_picker(callback, mime_type="*/*"):
    """Ouvre le sélecteur de fichier natif Android ou un FilePopup sur desktop."""
    global _file_picker_callback
    if ANDROID and HAS_JNIUS:
        _file_picker_callback = callback
        Intent         = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType(mime_type)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        PythonActivity.mActivity.startActivityForResult(intent, 42)
    else:
        # Desktop : popup Kivy classique
        if mime_type == "application/pdf":
            filters = ["*.pdf"]
        else:
            filters = ["*.png", "*.jpg", "*.jpeg"]
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
        start_path = self._get_start_path()
        self.chooser = FileChooserListView(
            path=start_path,
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

        # Toggle Noir & Blanc / Couleurs
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
        open_file_picker(self._on_pdf_selected, mime_type="application/pdf")

    def _on_pdf_selected(self, path):
        app = App.get_running_app()
        app.pdf_path    = path
        app.parafe_rect = None
        app.sig_rect    = None
        # Récupérer le vrai nom depuis l'URI si dispo, sinon basename du path
        display_name = os.path.basename(path)
        # Sur Android le path peut être un tmp genre tmpXXXX.pdf — on garde le nom affiché
        app.pdf_display_name = display_name
        self.pdf_label.text  = display_name
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
            "pdf_name":     getattr(app, "pdf_display_name", os.path.basename(app.pdf_path)),
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

            base = os.path.splitext(p["pdf_name"])[0]

            # Dossier de sortie garanti en écriture
            if ANDROID and HAS_JNIUS:
                Environment = autoclass("android.os.Environment")
                dl_dir = Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS
                )
                out_dir = dl_dir.getAbsolutePath()
            else:
                out_dir = os.path.dirname(p["pdf_path"])

            out_path = os.path.join(out_dir, base + "_scan.pdf")

            Clock.schedule_once(lambda dt: self._prog("Encodage PDF..."))
            pil_list_to_pdf(out_images, out_path)

            # Notifier MediaStore pour que le fichier soit visible partout
            if ANDROID and HAS_JNIUS:
                try:
                    MediaScannerConnection = autoclass(
                        "android.media.MediaScannerConnection")
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    MediaScannerConnection.scanFile(
                        PythonActivity.mActivity,
                        [out_path], ["application/pdf"], None
                    )
                except Exception:
                    pass

            Clock.schedule_once(lambda dt, o=out_path: self._on_done(o))

        except Exception as exc:
            import traceback
            err = traceback.format_exc()
            Clock.schedule_once(lambda dt, e=err: self._on_error(e))

    def _on_done(self, out_path):
        self._reset_btn()
        # Popup avec chemin + bouton Ouvrir
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        content.add_widget(Label(
            text="PDF genere :\n" + out_path,
            font_size=FS_POPUP, halign="center",
            text_size=(Window.width * 0.75, None),
            size_hint_y=None, height=dp(80),
        ))
        btn_row = BoxLayout(size_hint_y=None, height=H_BTN, spacing=dp(8))

        popup = Popup(
            title="Termine",
            content=content,
            size_hint=(0.88, None),
            height=dp(220),
        )

        def _open_pdf(_):
            popup.dismiss()
            if ANDROID and HAS_JNIUS:
                try:
                    Intent        = autoclass("android.content.Intent")
                    Uri           = autoclass("android.net.Uri")
                    File          = autoclass("java.io.File")
                    FileProvider  = autoclass(
                        "androidx.core.content.FileProvider")
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    ctx     = PythonActivity.mActivity
                    pkg     = ctx.getPackageName()
                    f       = File(out_path)
                    uri     = FileProvider.getUriForFile(
                        ctx, pkg + ".fileprovider", f)
                    intent  = Intent(Intent.ACTION_VIEW)
                    intent.setDataAndType(uri, "application/pdf")
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    ctx.startActivity(intent)
                except Exception as exc:
                    self._toast("Ouvrir avec :\n" + out_path, duration=6)

        btn_open  = make_btn("Ouvrir le PDF",  bg=C_GREEN,    fg=C_WHITE,
                             on_press=_open_pdf)
        btn_close = make_btn("Fermer",         bg=C_GREY_BTN, fg=C_TEXT_DARK,
                             on_press=lambda _: popup.dismiss())
        btn_row.add_widget(btn_open)
        btn_row.add_widget(btn_close)
        content.add_widget(btn_row)
        popup.open()

    def _on_error(self, err):
        self._reset_btn()
        Popup(
            title="Erreur",
            content=Label(text=err, font_size=FS_POPUP,
                          text_size=(Window.width * 0.85, None)),
            size_hint=(0.9, 0.7)
        ).open()

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
            auto_dismiss=True,
            separator_height=0,
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
        self.parafe_path = None
        self.sig_path    = None
        self.total_pages = 999
        self.parafe_rect = None
        self.sig_rect    = None

        if ANDROID and not HAS_JNIUS:
            return Label(
                text="[b]Erreur :[/b]\nJnius non disponible.",
                markup=True, halign="center", font_size=FS_POPUP
            )
        if not ANDROID and not HAS_FITZ:
            return Label(
                text="[b]Erreur :[/b]\nPyMuPDF non installe.\n\npip install pymupdf",
                markup=True, halign="center", font_size=FS_POPUP
            )

        self.sm = ScreenManager()
        self.main_screen   = MainScreen(name="main")
        self.picker_screen = PickerScreen(name="picker")
        self.sm.add_widget(self.main_screen)
        self.sm.add_widget(self.picker_screen)
        return self.sm


if __name__ == "__main__":
    FakeScanApp().run()
