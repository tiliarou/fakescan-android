"""
Fake Scan PDF — Android (Kivy)
================================
Dépendances Python :
    pip install kivy pymupdf pillow numpy plyer

Compiler en APK :
    pip install buildozer
    buildozer android debug   (depuis le dossier du projet)

Structure :
    MainScreen  → sélection fichiers, pages, effets, génération
    PickerScreen → dessin des zones parafe/signature sur aperçu PDF
"""

import io
import os
import random
import threading

# ── Kivy config (avant tout import kivy) ──────────────────────────────────
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
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scatter import Scatter
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from PIL import Image, ImageFilter, ImageEnhance, ImageOps

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


# ─────────────────────────────────────────────────────────────────────────
# COULEURS / STYLES GLOBAUX
# ─────────────────────────────────────────────────────────────────────────

C_BG        = (0.97, 0.97, 0.97, 1)
C_HEADER    = (0.18, 0.18, 0.22, 1)
C_GREEN     = (0.26, 0.63, 0.28, 1)
C_ORANGE    = (1.00, 0.60, 0.00, 1)
C_PURPLE    = (0.49, 0.11, 0.64, 1)
C_RED       = (0.80, 0.20, 0.20, 1)
C_GREY_BTN  = (0.88, 0.88, 0.88, 1)
C_WHITE     = (1, 1, 1, 1)
C_TEXT_DARK = (0.15, 0.15, 0.15, 1)


def make_btn(text, bg=C_GREY_BTN, fg=C_TEXT_DARK, size_hint_x=1,
             height=44, bold=False, on_press=None):
    btn = Button(
        text=text,
        background_normal="",
        background_color=bg,
        color=fg,
        size_hint=(size_hint_x, None),
        height=height,
        bold=bold,
        font_size="13sp",
    )
    if on_press:
        btn.bind(on_press=on_press)
    return btn


def make_label(text, color=C_TEXT_DARK, font_size="12sp",
               size_hint_y=None, height=28, halign="left", italic=False):
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
        text=f"[b]{text}[/b]",
        markup=True,
        color=C_HEADER,
        font_size="13sp",
        size_hint_y=None,
        height=32,
        halign="left",
    )
    lbl.bind(size=lambda inst, v: setattr(inst, "text_size", v))
    return lbl


# ─────────────────────────────────────────────────────────────────────────
# STRUCTURE RECT
# ─────────────────────────────────────────────────────────────────────────

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
        return f"Rect({self.x1},{self.y1}→{self.x2},{self.y2} [{self.w}×{self.h}])"


# ─────────────────────────────────────────────────────────────────────────
# TRAITEMENT IMAGE
# ─────────────────────────────────────────────────────────────────────────

def vary_signature(base_img):
    """Variante aléatoire d'une image de signature — random pur, continu entre pages."""
    sig = base_img.copy()
    sig = sig.rotate(random.uniform(-1.2, 1.2), expand=True, fillcolor=(0, 0, 0, 0))
    sig = ImageEnhance.Contrast(sig).enhance(random.uniform(0.88, 1.12))
    if HAS_NUMPY:
        arr  = np.array(sig)
        mask = arr[:, :, 3] > 30
        ns   = random.randint(4, 10)
        noise = np.random.randint(-ns, ns + 1, arr[:, :, :3].shape, dtype=np.int16)
        rgb   = arr[:, :, :3].astype(np.int16)
        rgb[mask] = np.clip(rgb[mask] + noise[mask], 0, 255)
        arr[:, :, :3] = rgb.astype(np.uint8)
        sig = Image.fromarray(arr, "RGBA")
    sig = sig.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.05, 0.55)))
    return sig


def fit_into_rect(img, rect, jitter=True):
    """Redimensionne img pour tenir dans rect, centré. Retourne (img, x, y)."""
    scale = min(rect.w / img.width, rect.h / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    img_r  = img.resize((nw, nh), Image.Resampling.LANCZOS)
    cx = rect.x1 + (rect.w - nw) // 2
    cy = rect.y1 + (rect.h - nh) // 2
    if jitter:
        cx += random.randint(-3, 3)
        cy += random.randint(-3, 3)
    return img_r, cx, cy


def simulate_scan(img, tilt=1.2, blur=0.3, contrast=1.1, brightness=1.0):
    img = img.rotate(random.uniform(-tilt, tilt), expand=True, fillcolor=(255, 255, 255))
    img = ImageOps.grayscale(img)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    if HAS_NUMPY:
        arr = np.array(img).astype(np.int16)
        arr = np.clip(arr + np.random.randint(-4, 5, arr.shape, dtype=np.int16), 0, 255).astype(np.uint8)
        img = Image.fromarray(arr, "L")
    img = ImageEnhance.Contrast(img).enhance(contrast    + random.uniform(-0.05,  0.05))
    img = ImageEnhance.Brightness(img).enhance(brightness + random.uniform(-0.02,  0.02))
    w, h = img.size
    img  = img.resize((int(w * 0.95), int(h * 0.95)), Image.Resampling.LANCZOS)
    img  = img.resize((w, h), Image.Resampling.LANCZOS)
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


# ─────────────────────────────────────────────────────────────────────────
# PDF HELPERS (PyMuPDF)
# ─────────────────────────────────────────────────────────────────────────

DPI_PREVIEW = 100
DPI_PROCESS = 250

def pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW):
    """Convertit une page PDF en image PIL via PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


def pdf_to_pil_list(pdf_path, dpi=DPI_PROCESS):
    """Convertit toutes les pages d'un PDF en liste d'images PIL."""
    doc    = fitz.open(pdf_path)
    mat    = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    doc.close()
    return images


def pil_list_to_pdf(images, out_path):
    """Sauvegarde une liste d'images PIL en PDF via PyMuPDF."""
    doc = fitz.open()
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        img_doc = fitz.open("png", buf.read())
        doc.insert_pdf(img_doc)
        img_doc.close()
    doc.save(out_path)
    doc.close()


def pil_to_kivy_texture(pil_img):
    """Convertit une image PIL en texture Kivy."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data    = pil_img.tobytes()
    texture = Texture.create(size=(pil_img.width, pil_img.height), colorfmt="rgba")
    # Kivy a l'axe Y inversé
    texture.blit_buffer(data, colorfmt="rgba", bufferfmt="ubyte")
    texture.flip_vertical()
    return texture


# ─────────────────────────────────────────────────────────────────────────
# WIDGET : ZONE DE DESSIN RECTANGLES (PickerCanvas)
# ─────────────────────────────────────────────────────────────────────────

class PickerCanvas(Widget):
    """
    Affiche une page PDF et permet à l'utilisateur de dessiner deux
    rectangles par glissement tactile (parafe violet, signature vert).
    """

    COLOR_PARAFE = (0.62, 0.14, 0.80, 0.45)
    COLOR_SIG    = (0.18, 0.63, 0.18, 0.45)
    OUTLINE_P    = (0.62, 0.14, 0.80, 1.0)
    OUTLINE_S    = (0.18, 0.63, 0.18, 1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode          = None      # "parafe" | "sig"
        self.preview_pil   = None
        self.preview_w     = 1
        self.preview_h     = 1
        self.scale_factor  = 1.0       # canvas px / preview px
        self.dpi_ratio     = DPI_PROCESS / DPI_PREVIEW

        # Rects en coordonnées canvas
        self._rect_parafe_canvas = None   # (x1,y1,x2,y2) canvas
        self._rect_sig_canvas    = None

        # Rects en coordonnées réelles (250 dpi)
        self.rect_parafe = None   # Rect
        self.rect_sig    = None

        self._drag_start  = None
        self._live_coords = None   # (x1,y1,x2,y2) du rect en cours

        self.bind(size=self._redraw, pos=self._redraw)

    # ── Image ──────────────────────────────────────────────────────────────

    def set_preview(self, pil_img):
        """Charge l'image de prévisualisation et la dessine."""
        self.preview_pil = pil_img
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        if not self.preview_pil:
            return

        # Calculer le scale pour faire tenir l'image dans le widget
        sw = self.width  / self.preview_pil.width
        sh = self.height / self.preview_pil.height
        self.scale_factor = min(sw, sh)

        dw = int(self.preview_pil.width  * self.scale_factor)
        dh = int(self.preview_pil.height * self.scale_factor)

        # Centrage
        self._offset_x = (self.width  - dw) / 2 + self.x
        self._offset_y = (self.height - dh) / 2 + self.y
        self.preview_w = dw
        self.preview_h = dh

        tex = pil_to_kivy_texture(self.preview_pil)
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=tex,
                      pos=(self._offset_x, self._offset_y),
                      size=(dw, dh))

        # Re-dessiner les rects enregistrés
        if self._rect_parafe_canvas:
            self._draw_rect_canvas(*self._rect_parafe_canvas,
                                   self.COLOR_PARAFE, self.OUTLINE_P, "P")
        if self._rect_sig_canvas:
            self._draw_rect_canvas(*self._rect_sig_canvas,
                                   self.COLOR_SIG,    self.OUTLINE_S, "S")

        # Rect en cours de dessin
        if self._live_coords:
            c = self.COLOR_PARAFE if self.mode == "parafe" else self.COLOR_SIG
            o = self.OUTLINE_P    if self.mode == "parafe" else self.OUTLINE_S
            self._draw_rect_canvas(*self._live_coords, c, o, "")

    def _draw_rect_canvas(self, cx1, cy1, cx2, cy2, fill_color, outline_color, label):
        x, y   = min(cx1, cx2), min(cy1, cy2)
        w, h   = abs(cx2 - cx1), abs(cy2 - cy1)
        with self.canvas:
            Color(*fill_color)
            Rectangle(pos=(x, y), size=(w, h))
            Color(*outline_color)
            Line(rectangle=(x, y, w, h), width=2)

    # ── Coordonnées ────────────────────────────────────────────────────────

    def _canvas_to_preview(self, cx, cy):
        """Coordonnées canvas → pixels preview (DPI_PREVIEW)."""
        px = (cx - self._offset_x) / self.scale_factor
        py = (cy - self._offset_y) / self.scale_factor
        return px, py

    def _canvas_to_real(self, cx, cy):
        """Coordonnées canvas → pixels réels (DPI_PROCESS)."""
        px, py = self._canvas_to_preview(cx, cy)
        return int(px * self.dpi_ratio), int(py * self.dpi_ratio)

    # ── Touch ───────────────────────────────────────────────────────────────

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
            return True   # glissement trop court

        # Convertir en coordonnées réelles
        rx0, ry0 = self._canvas_to_real(min(x0, x1), min(y0, y1))
        rx1, ry1 = self._canvas_to_real(max(x0, x1), max(y0, y1))

        # Note : Kivy Y est de bas en haut, PDF Y est de haut en bas
        # On récupère la hauteur réelle de la page pour inverser Y
        if self.preview_pil:
            real_h = int(self.preview_pil.height * self.dpi_ratio)
            ry0_f  = real_h - ry1
            ry1_f  = real_h - ry0
        else:
            ry0_f, ry1_f = ry0, ry1

        rect = Rect(rx0, ry0_f, rx1, ry1_f)

        if self.mode == "parafe":
            self.rect_parafe          = rect
            self._rect_parafe_canvas  = (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))
        else:
            self.rect_sig             = rect
            self._rect_sig_canvas     = (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))

        self._redraw()
        return True

    def clear_rects(self):
        self._rect_parafe_canvas = None
        self._rect_sig_canvas    = None
        self.rect_parafe         = None
        self.rect_sig            = None
        self._redraw()


# ─────────────────────────────────────────────────────────────────────────
# ÉCRAN PICKER
# ─────────────────────────────────────────────────────────────────────────

class PickerScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", spacing=0)

        # ── Barre de boutons ───────────────────────────────────────────────
        bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=50,
                        spacing=4, padding=(4, 4))
        with bar.canvas.before:
            Color(*C_HEADER)
            self._bar_bg = Rectangle()
        bar.bind(size=lambda w, v: setattr(self._bar_bg, "size", v),
                 pos =lambda w, v: setattr(self._bar_bg, "pos",  v))

        self.btn_parafe = make_btn("✍ PARAFE",  bg=(0.49, 0.11, 0.64, 1),
                                   fg=C_WHITE, on_press=lambda _: self._set_mode("parafe"))
        self.btn_sig    = make_btn("🖊 SIGNATURE", bg=(0.18, 0.63, 0.28, 1),
                                   fg=C_WHITE, on_press=lambda _: self._set_mode("sig"))
        btn_clear = make_btn("🗑", bg=C_RED, fg=C_WHITE, size_hint_x=0.25,
                             on_press=lambda _: self._clear())
        btn_ok    = make_btn("✅ OK", bg=C_GREEN, fg=C_WHITE, size_hint_x=0.45,
                             on_press=lambda _: self._validate())

        for w in (self.btn_parafe, self.btn_sig, btn_clear, btn_ok):
            bar.add_widget(w)
        root.add_widget(bar)

        # ── Statut ─────────────────────────────────────────────────────────
        self.status_lbl = make_label(
            "Choisir un mode, puis glisser pour délimiter la zone",
            color=(0.3, 0.3, 0.3, 1), height=30, halign="center"
        )
        root.add_widget(self.status_lbl)

        # ── Canvas de dessin ───────────────────────────────────────────────
        self.picker = PickerCanvas()
        root.add_widget(self.picker)

        self.add_widget(root)

    def _set_mode(self, mode):
        self.picker.mode = mode
        txt = {"parafe": "✍ Mode PARAFE actif — glisser pour délimiter",
               "sig":    "🖊 Mode SIGNATURE actif — glisser pour délimiter"}
        self.status_lbl.text = txt[mode]

    def _clear(self):
        self.picker.clear_rects()
        self.picker.mode = None
        self.status_lbl.text = "Zones effacées. Choisir un mode."

    def _validate(self):
        app = App.get_running_app()
        app.parafe_rect = self.picker.rect_parafe
        app.sig_rect    = self.picker.rect_sig
        app.sm.transition = SlideTransition(direction="right")
        app.sm.current = "main"
        app.main_screen.refresh_zones_label()

    def load_pdf_preview(self, pdf_path):
        """Chargé depuis MainScreen après sélection du PDF."""
        try:
            img = pdf_page_to_pil(pdf_path, page_index=0, dpi=DPI_PREVIEW)
            self.picker.set_preview(img)
            # Restaurer les rects existants si on revient sur cet écran
            app = App.get_running_app()
            self.picker.rect_parafe = app.parafe_rect
            self.picker.rect_sig    = app.sig_rect
        except Exception as exc:
            self.status_lbl.text = f"Erreur aperçu : {exc}"


# ─────────────────────────────────────────────────────────────────────────
# WIDGET : FILE CHOOSER POPUP
# ─────────────────────────────────────────────────────────────────────────

class FilePopup(Popup):

    def __init__(self, callback, filters=None, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        self.title    = "Choisir un fichier"
        self.size_hint = (0.95, 0.85)

        layout = BoxLayout(orientation="vertical", spacing=8, padding=8)

        start_path = self._get_start_path()
        self.chooser = FileChooserListView(
            path=start_path,
            filters=filters or ["*"],
            size_hint_y=1,
        )
        layout.add_widget(self.chooser)

        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        btn_row.add_widget(make_btn("Annuler", bg=C_RED, fg=C_WHITE,
                                    on_press=lambda _: self.dismiss()))
        btn_row.add_widget(make_btn("Sélectionner", bg=C_GREEN, fg=C_WHITE,
                                    on_press=self._select))
        layout.add_widget(btn_row)
        self.content = layout

    @staticmethod
    def _get_start_path():
        # Sur Android : /sdcard/  ou  /storage/emulated/0/
        for p in ("/sdcard", "/storage/emulated/0", os.path.expanduser("~")):
            if os.path.isdir(p):
                return p
        return "/"

    def _select(self, *_):
        sel = self.chooser.selection
        if sel:
            self.dismiss()
            self.callback(sel[0])


# ─────────────────────────────────────────────────────────────────────────
# SLIDER NOMMÉ (label + slider + valeur)
# ─────────────────────────────────────────────────────────────────────────

class NamedSlider(BoxLayout):

    def __init__(self, label, lo, hi, value, step=0.05, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=40, spacing=6, **kwargs)
        self._lbl = make_label(label, height=40, halign="left")
        self._lbl.size_hint_x = 0.38

        self.slider = Slider(min=lo, max=hi, value=value, step=step,
                             size_hint_x=0.44)
        self._val_lbl = make_label(f"{value:.2f}", height=40,
                                   halign="right")
        self._val_lbl.size_hint_x = 0.18

        self.slider.bind(value=self._on_value)
        self.add_widget(self._lbl)
        self.add_widget(self.slider)
        self.add_widget(self._val_lbl)

    def _on_value(self, inst, v):
        self._val_lbl.text = f"{v:.2f}"

    @property
    def value(self):
        return self.slider.value


# ─────────────────────────────────────────────────────────────────────────
# ÉCRAN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────

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

        # ── Header ─────────────────────────────────────────────────────────
        header = BoxLayout(size_hint_y=None, height=52, padding=(12, 8))
        with header.canvas.before:
            Color(*C_HEADER)
            self._hbg = Rectangle()
        header.bind(size=lambda w, v: setattr(self._hbg, "size", v),
                    pos =lambda w, v: setattr(self._hbg, "pos",  v))
        header.add_widget(Label(text="[b]🖨 Fake Scan PDF[/b]", markup=True,
                                color=C_WHITE, font_size="16sp", halign="left"))
        outer.add_widget(header)

        # ── Contenu scrollable ─────────────────────────────────────────────
        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        content = BoxLayout(orientation="vertical", spacing=10,
                            padding=(12, 10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # ── Section Fichiers ───────────────────────────────────────────────
        content.add_widget(section_label("📂  Fichiers"))

        # PDF
        row_pdf = BoxLayout(size_hint_y=None, height=44, spacing=6)
        row_pdf.add_widget(make_btn("📄 PDF", bg=(0.88, 0.96, 1, 1),
                                    size_hint_x=0.38,
                                    on_press=lambda _: self._pick_pdf()))
        self.pdf_label = make_label("Aucun PDF", color=(0.5, 0.5, 0.5, 1),
                                    height=44)
        row_pdf.add_widget(self.pdf_label)
        content.add_widget(row_pdf)

        # Bouton Picker zones
        self.btn_picker = make_btn("🖱 Définir les zones (parafe / signature)",
                                   bg=C_ORANGE, fg=C_WHITE, height=44,
                                   on_press=lambda _: self._open_picker())
        self.btn_picker.disabled = True
        content.add_widget(self.btn_picker)

        self.zones_label = make_label(
            "Zones : non définies",
            color=(0.55, 0.35, 0.65, 1), height=28, italic=True
        )
        content.add_widget(self.zones_label)

        # Parafe
        row_p = BoxLayout(size_hint_y=None, height=44, spacing=6)
        row_p.add_widget(make_btn("✍ Parafe", bg=(0.96, 0.90, 1.00, 1),
                                   size_hint_x=0.38,
                                   on_press=lambda _: self._pick_parafe()))
        self.parafe_label = make_label("Aucune image", color=(0.5, 0.5, 0.5, 1),
                                       height=44)
        row_p.add_widget(self.parafe_label)
        content.add_widget(row_p)

        # Signature
        row_s = BoxLayout(size_hint_y=None, height=44, spacing=6)
        row_s.add_widget(make_btn("🖊 Signature", bg=(0.90, 0.97, 0.90, 1),
                                   size_hint_x=0.38,
                                   on_press=lambda _: self._pick_sig()))
        self.sig_label = make_label("Aucune image", color=(0.5, 0.5, 0.5, 1),
                                    height=44)
        row_s.add_widget(self.sig_label)
        content.add_widget(row_s)

        # ── Section Pages ──────────────────────────────────────────────────
        content.add_widget(section_label("📄  Pages  (ex : 1  ou  1,3-5,7)"))

        row_pp = BoxLayout(size_hint_y=None, height=40, spacing=6)
        row_pp.add_widget(make_label("Parafe :", height=40, halign="left"))
        self.parafe_pages = TextInput(text="1", multiline=False,
                                      size_hint_y=None, height=40,
                                      font_size="14sp")
        row_pp.add_widget(self.parafe_pages)
        content.add_widget(row_pp)

        row_sp = BoxLayout(size_hint_y=None, height=40, spacing=6)
        row_sp.add_widget(make_label("Signature :", height=40, halign="left"))
        self.sig_pages = TextInput(text="1", multiline=False,
                                   size_hint_y=None, height=40,
                                   font_size="14sp")
        row_sp.add_widget(self.sig_pages)
        content.add_widget(row_sp)

        # ── Section Effets scan ────────────────────────────────────────────
        content.add_widget(section_label("🎛  Effets scan"))

        self.sl_tilt      = NamedSlider("Tilt (°)",   0.0, 3.0, 1.2, 0.1)
        self.sl_blur      = NamedSlider("Flou",       0.0, 2.0, 0.3, 0.05)
        self.sl_contrast  = NamedSlider("Contraste",  0.7, 1.6, 1.1, 0.05)
        self.sl_brightness= NamedSlider("Luminosité", 0.7, 1.3, 1.0, 0.05)
        for w in (self.sl_tilt, self.sl_blur, self.sl_contrast, self.sl_brightness):
            content.add_widget(w)

        # ── Bouton Générer ─────────────────────────────────────────────────
        self.btn_gen = make_btn("🚀  GÉNÉRER PDF SCAN", bg=C_GREEN, fg=C_WHITE,
                                height=56, bold=True,
                                on_press=lambda _: self._run())
        content.add_widget(self.btn_gen)

        self.progress_lbl = make_label("", color=(0.4, 0.4, 0.4, 1),
                                       height=28, halign="center", italic=True)
        content.add_widget(self.progress_lbl)

        # Espaceur bas
        content.add_widget(Widget(size_hint_y=None, height=20))

        scroll.add_widget(content)
        outer.add_widget(scroll)
        self.add_widget(outer)

    # ── File picking ───────────────────────────────────────────────────────

    def _pick_pdf(self):
        FilePopup(self._on_pdf_selected, filters=["*.pdf"]).open()

    def _on_pdf_selected(self, path):
        app = App.get_running_app()
        app.pdf_path     = path
        app.parafe_rect  = None
        app.sig_rect     = None
        self.pdf_label.text  = os.path.basename(path)
        self.pdf_label.color = (0.10, 0.14, 0.55, 1)
        self.btn_picker.disabled = False
        # Compter les pages
        try:
            doc = fitz.open(path)
            app.total_pages = len(doc)
            doc.close()
        except Exception:
            app.total_pages = 999
        self.refresh_zones_label()

    def _pick_parafe(self):
        FilePopup(self._on_parafe_selected,
                  filters=["*.png", "*.jpg", "*.jpeg"]).open()

    def _on_parafe_selected(self, path):
        App.get_running_app().parafe_path = path
        self.parafe_label.text  = os.path.basename(path)
        self.parafe_label.color = (0.30, 0.05, 0.40, 1)

    def _pick_sig(self):
        FilePopup(self._on_sig_selected,
                  filters=["*.png", "*.jpg", "*.jpeg"]).open()

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
        app  = App.get_running_app()
        parts = []
        if app.parafe_rect:
            r = app.parafe_rect
            parts.append(f"✍ Parafe {r.w}×{r.h}px")
        else:
            parts.append("✍ Parafe : non défini")
        if app.sig_rect:
            r = app.sig_rect
            parts.append(f"🖊 Sig {r.w}×{r.h}px")
        else:
            parts.append("🖊 Sig : non défini")
        self.zones_label.text = "  |  ".join(parts)

    # ── Génération ─────────────────────────────────────────────────────────

    def _run(self):
        app = App.get_running_app()
        if not app.pdf_path:
            self._toast("Sélectionne un PDF"); return
        if not app.parafe_path and not app.sig_path:
            self._toast("Sélectionne au moins une image"); return
        if app.parafe_path and not app.parafe_rect:
            self._toast("Définis la zone du parafe via 🖱"); return
        if app.sig_path and not app.sig_rect:
            self._toast("Définis la zone de la signature via 🖱"); return

        self.btn_gen.disabled = True
        self.btn_gen.text     = "⏳ Traitement…"
        self._prog("Démarrage…")

        params = {
            "pdf_path":     app.pdf_path,
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
        }
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, p):
        try:
            Clock.schedule_once(lambda dt: self._prog("📄 Conversion du PDF…"))

            images = pdf_to_pil_list(p["pdf_path"], dpi=DPI_PROCESS)
            total  = len(images)

            parafe_base = Image.open(p["parafe_path"]).convert("RGBA") if p["parafe_path"] else None
            sig_base    = Image.open(p["sig_path"]).convert("RGBA")    if p["sig_path"]    else None

            out_images = []
            for idx, page_img in enumerate(images):
                page_num = idx + 1
                Clock.schedule_once(
                    lambda dt, n=page_num, t=total: self._prog(f"🖨 Page {n}/{t}…")
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
                )
                out_images.append(page_img.convert("RGB"))

            # Chemin de sortie
            base    = os.path.splitext(os.path.basename(p["pdf_path"]))[0]
            out_dir = os.path.dirname(p["pdf_path"])
            out_path= os.path.join(out_dir, f"{base}_scan.pdf")

            Clock.schedule_once(lambda dt: self._prog("💾 Encodage PDF…"))
            pil_list_to_pdf(out_images, out_path)

            Clock.schedule_once(lambda dt, o=out_path: self._on_done(o))

        except Exception as exc:
            import traceback
            err = traceback.format_exc()
            Clock.schedule_once(lambda dt, e=err: self._on_error(e))

    def _on_done(self, out_path):
        self._reset_btn()
        self._toast(f"✅ PDF généré :\n{os.path.basename(out_path)}", duration=4)

    def _on_error(self, err):
        self._reset_btn()
        Popup(
            title="Erreur",
            content=Label(text=err, font_size="10sp", text_size=(Window.width * 0.85, None)),
            size_hint=(0.9, 0.7)
        ).open()

    def _reset_btn(self):
        self.btn_gen.disabled = False
        self.btn_gen.text     = "🚀  GÉNÉRER PDF SCAN"
        self._prog("")

    def _prog(self, msg):
        self.progress_lbl.text = msg

    def _toast(self, msg, duration=2.5):
        pop = Popup(
            title="",
            content=Label(text=msg, halign="center", font_size="13sp"),
            size_hint=(0.8, None), height=120,
            auto_dismiss=True,
            separator_height=0,
        )
        pop.open()
        Clock.schedule_once(lambda dt: pop.dismiss(), duration)


# ─────────────────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────────────────

class FakeScanApp(App):

    def build(self):
        # État global
        self.pdf_path    = None
        self.parafe_path = None
        self.sig_path    = None
        self.total_pages = 999
        self.parafe_rect = None
        self.sig_rect    = None

        # Vérification dépendance critique
        if not HAS_FITZ:
            from kivy.uix.label import Label
            return Label(
                text="[b]Erreur :[/b]\nPyMuPDF (fitz) non installé.\n\npip install pymupdf",
                markup=True, halign="center", font_size="14sp"
            )

        self.sm = ScreenManager()

        self.main_screen   = MainScreen(name="main")
        self.picker_screen = PickerScreen(name="picker")

        self.sm.add_widget(self.main_screen)
        self.sm.add_widget(self.picker_screen)

        return self.sm


if __name__ == "__main__":
    FakeScanApp().run()
