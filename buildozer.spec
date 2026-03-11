[app]

# ── Identite ──────────────────────────────────────────────────────────────
title           = Fake Scan PDF
package.name    = fakescanpdf
package.domain  = org.fakescan
version         = 1.0

# ── Code source ─────────────────────────────────────────────────────────────
source.dir      = .
source.include_exts = py,png,jpg,jpeg,kv,atlas

# ── Point d'entree ──────────────────────────────────────────────────────────
entrypoint      = main.py

# ── Dependances Python ────────────────────────────────────────────────────────
requirements    = python3,kivy==2.3.0,pillow,plyer

# ── Android ────────────────────────────────────────────────────────────────
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,\
                      READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.api         = 33
android.minapi      = 26
android.build_tools_version = 34.0.0
android.ndk         = 25b
android.archs       = arm64-v8a, armeabi-v7a
android.allow_backup = False
android.release_artifact = apk

# Orientation portrait uniquement
orientation     = portrait

# Icone (optionnel - remplacer par votre fichier)
# icon.filename = %(source.dir)s/icon.png

# ── Signature release ──────────────────────────────────────────────────────────
# Le fichier fakescan.keystore doit etre dans le meme dossier que ce spec.
# Ne jamais commiter fakescan.keystore dans git (voir .gitignore).
# Remplacer YOUR_PASSWORD par votre mot de passe reel en local.
android.keystore        = fakescan.keystore
android.keystore_alias  = fakescan
android.keystore_passwd = YOUR_PASSWORD
android.keyalias_passwd = YOUR_PASSWORD

# ── Build ───────────────────────────────────────────────────────────────────
[buildozer]
log_level   = 2
warn_on_root = 1

p4a.local_recipes = ./p4a-recipes
android.add_resource = res/
