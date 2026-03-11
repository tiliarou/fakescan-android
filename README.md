# Fake Scan PDF — Android

[![Build Android APK](https://github.com/tiliarou/fakescan-android/actions/workflows/build_apk.yml/badge.svg)](https://github.com/tiliarou/fakescan-android/actions/workflows/build_apk.yml)

Application Android (Kivy + Pillow) qui simule un document imprimé, signé puis scanné.

---

## Télécharger l'APK

→ Onglet **[Releases](../../releases)** pour les versions taguées  
→ Onglet **[Actions](../../actions)** → dernier run → section **Artifacts** pour les builds de développement

---

## Fonctionnement

1. **📄 PDF** — sélectionner le PDF à traiter
2. **🖱 Définir les zones** — ouvre l'aperçu de la page 1 :
   - Appuyer **✍ PARAFE** puis glisser pour délimiter la zone
   - Appuyer **🖊 SIGNATURE** puis glisser pour délimiter la zone
   - **✅ OK** pour valider
3. **✍ Parafe / 🖊 Signature** — sélectionner les images PNG/JPG
4. Saisir les **pages** (`1`, `1,3-5,7`, etc.)
5. Ajuster les sliders d'effets
6. **🚀 GÉNÉRER** — le PDF est sauvegardé dans le même dossier avec le suffixe `_scan.pdf`

---

## CI/CD — GitHub Actions

| Déclencheur | Action |
|---|---|
| Push sur `main` | Build APK release → artefact téléchargeable 30 jours |
| Pull Request vers `main` | Build APK release (validation) |
| Tag `vX.Y.Z` (ex: `v1.0.0`) | Build APK release + création GitHub Release automatique |
| Manuel (workflow_dispatch) | Build à la demande depuis l'onglet Actions |

### Secrets requis

Le CI nécessite 3 secrets GitHub (Settings → Secrets and variables → Actions) :

| Secret | Description |
|---|---|
| `KEYSTORE_B64` | Keystore encodé en base64 (`base64 -w 0 fakescan.keystore`) |
| `KEYSTORE_PASSWD` | Mot de passe du keystore |
| `KEYALIAS_PASSWD` | Mot de passe de l'alias |

### Créer une Release

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions compile l'APK signé et crée automatiquement une Release avec le fichier `.apk` en pièce jointe.

---

## Développement local

### Tester sur PC (sans compiler)

```bash
pip install kivy pillow plyer
python main.py
```

### Compiler l'APK manuellement (Linux / WSL2)

```bash
# Dépendances système
sudo apt-get install -y python3-pip git zip unzip openjdk-17-jdk \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev cmake \
  libffi-dev libssl-dev build-essential

# Buildozer
pip install buildozer cython

# Générer le keystore (une seule fois)
keytool -genkey -v -keystore fakescan.keystore \
  -alias fakescan -keyalg RSA -keysize 2048 -validity 10000

# Renseigner les mots de passe dans buildozer.spec
# (remplacer YOUR_PASSWORD par le vrai mot de passe)

# Build release
buildozer android release

# Installer sur téléphone (ADB)
adb install bin/fakescanpdf-1.0-arm64-v8a_armeabi-v7a-release.apk
```

---

## Stack technique

| Package | Rôle |
|---|---|
| [Kivy](https://kivy.org) | UI multiplateforme / Android |
| [Pillow](https://pillow.readthedocs.io) | Lecture PDF, traitement image |
| [Plyer](https://plyer.readthedocs.io) | Accès fichiers natifs Android |
| [Buildozer](https://buildozer.readthedocs.io) | Compilation APK |
