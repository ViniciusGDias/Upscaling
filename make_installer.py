"""
Urahara - Build & Installer Orchestrator
Automates:
1. Compiling Urahara (fast --onedir mode, no terminal window).
2. Compiling Urahara_Setup.exe using Inno Setup.
3. Creating a portable distribution package (ZIP) ready for GitHub Releases.
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

APP_DIR = Path(__file__).parent.resolve()
VERSION_FILE = APP_DIR / "version.json"


def get_version() -> str:
    try:
        import json
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "1.0.0")
    except Exception:
        return "1.0.0"


def find_inno_compiler() -> str:
    """Find ISCC.exe in system PATH or standard install locations."""
    found = shutil.which("iscc")
    if found:
        return found
    common_locations = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 5\ISCC.exe"),
    ]
    for p in common_locations:
        if p.exists():
            return str(p)
    return ""


def main():
    ver = get_version()
    print("=" * 60)
    print(f" [Urahara Studio v{ver}] - Gerador de Executavel & Instalador")
    print("=" * 60)

    # 1. Build EXE with PyInstaller (--onedir for instantaneous startup)
    print("\n[1/3] Compilando Urahara (Modo Janela / Inicialização Instantânea)...")
    res = subprocess.run([sys.executable, "build_exe.py"], cwd=str(APP_DIR))
    if res.returncode != 0:
        print("\n✕ Erro ao compilar com PyInstaller.")
        sys.exit(1)

    dist_folder = APP_DIR / "dist" / "Urahara"
    exe_path = dist_folder / "Urahara.exe"
    if not exe_path.exists():
        # Fallback to single exe if onedir not used
        exe_path = APP_DIR / "dist" / "Urahara.exe"
        if not exe_path.exists():
            print(f"\n✕ Executável não encontrado em {dist_folder} nem em dist/Urahara.exe.")
            sys.exit(1)

    print(f"\n✓ Executável Urahara.exe gerado com sucesso em: {exe_path}")

    # Copiar bin/ (FFmpeg, FFprobe, Real-CUGAN) para dist/Urahara/bin e dist/Urahara/_internal/bin
    bin_src = APP_DIR / "bin"
    if bin_src.exists() and dist_folder.exists():
        for target_dir in [dist_folder / "bin", dist_folder / "_internal" / "bin"]:
            target_dir.mkdir(parents=True, exist_ok=True)
            print(f"   📦 Copiando dependências de bin/ para {target_dir.relative_to(APP_DIR)}...")
            for item in bin_src.glob("*"):
                dest = target_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

    # 2. Compile Inno Setup for Setup.exe
    print("\n[2/3] Compilando instalador Setup.exe com Inno Setup...")
    iscc = find_inno_compiler()
    setup_created = False

    if iscc:
        print(f"   ✓ Inno Setup encontrado: {iscc}")
        iss_file = APP_DIR / "installer.iss"
        if iss_file.exists():
            res_iscc = subprocess.run([iscc, str(iss_file)], cwd=str(APP_DIR))
            if res_iscc.returncode == 0:
                setup_path = APP_DIR / "setup_output" / f"Urahara_Setup_v{ver}.exe"
                print(f"   🎉 Instalador criado com sucesso: {setup_path}")
                setup_created = True
            else:
                print("   ⚠️ Inno Setup retornou erro. Verifique a sintaxe de installer.iss.")
    else:
        print("   ℹ️ Inno Setup não está instalado no sistema.")

    # 3. Create Portable Release ZIP
    print("\n[3/3] Criando pacote portátil Urahara_v{ver}_Portable.zip...")
    out_dir = APP_DIR / "setup_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"Urahara_v{ver}_Portable.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if dist_folder.exists():
            # Add all files from dist/Urahara
            for root, _, files in os.walk(dist_folder):
                for f in files:
                    fp = Path(root) / f
                    rel = fp.relative_to(dist_folder)
                    zf.write(fp, f"Urahara/{rel}")
        else:
            zf.write(exe_path, "Urahara/Urahara.exe")

        zf.write(APP_DIR / "app_icon.ico", "Urahara/app_icon.ico")
        zf.write(APP_DIR / "app_icon.png", "Urahara/app_icon.png")
        zf.write(APP_DIR / "version.json", "Urahara/version.json")
        zf.write(APP_DIR / ".env.example", "Urahara/.env.example")
        if (APP_DIR / "README.md").exists():
            zf.write(APP_DIR / "README.md", "Urahara/README.md")

    print(f"✓ Pacote portátil criado: {zip_path}")
    print("\n" + "=" * 60)
    print(" 🎉 PROCESSO CONCLUÍDO!")
    if setup_created:
        print(f" 1. Instalador: setup_output/Urahara_Setup_v{ver}.exe")
    print(f" 2. Pasta com App Instantâneo: dist/Urahara/Urahara.exe")
    print(f" 3. Pacote para Release: setup_output/Urahara_v{ver}_Portable.zip")
    print("=" * 60)


if __name__ == "__main__":
    main()
