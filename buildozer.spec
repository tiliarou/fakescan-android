[app]

# ── Identité ───────────────────────────────────────────────────────────────
title           = Fake Scan PDF
package.name    = fakescanpdf
package.domain  = org.fakescan
version         = 1.0

# ── Code source ────────────────────────────────────────────────────────────
source.dir      = .
source.include_exts = py,png,jpg,jpeg,kv,atlas

# ── Point d'entrée ─────────────────────────────────────────────────────────
entrypoint      = main.py

# ── Dépendances Python ──────────────────────────────────────────────────────
# pymupdf remplace pdf2image (pas besoin de Poppler natif)
requirements    = python3,kivy==2.3.0,pillow,pymupdf,plyer

# ── Android ────────────────────────────────────────────────────────────────
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,\
                      READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.api         = 33
android.minapi      = 26
android.build_tools_version = 34.0.0
android.ndk         = 25b
android.archs       = arm64-v8a, armeabi-v7a
android.allow_backup = False

# Orientation portrait uniquement
orientation     = portrait

# Icône (optionnel — remplacer par votre fichier)
# icon.filename = %(source.dir)s/icon.png

# ── Build ───────────────────────────────────────────────────────────────────
[buildozer]
log_level   = 2
warn_on_root = 1
