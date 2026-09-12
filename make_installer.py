"""
Urahara - Build & Installer Orchestrator
Automates:
1. Compiling Urahara.exe using PyInstaller (with --noconsole, no terminal).
2. Compiling Urahara_Setup.exe using Inno Setup (if installed).
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

    # 1. Build EXE with PyInstaller
    print("\n[1/3] Compilando Urahara.exe (Modo Janela / Sem Terminal)...")
    res = subprocess.run([sys.executable, "build_exe.py"], cwd=str(APP_DIR))
    if res.returncode != 0:
        print("\n✕ Erro ao compilar com PyInstaller.")
        sys.exit(1)

    exe_path = APP_DIR / "dist" / "Urahara.exe"
    if not exe_path.exists():
        print(f"\n✕ Executável não encontrado em {exe_path}.")
        sys.exit(1)

    print(f"\n✓ Executável Urahara.exe gerado com sucesso em: {exe_path}")

    # 2. Check Inno Setup for setup.exe
    print("\n[2/3] Verificando Inno Setup para gerar Setup.exe...")
    iscc = find_inno_compiler()
    setup_created = False

    if iscc:
        print(f"   ✓ Inno Setup encontrado: {iscc}")
        print("   Compilando Urahara_Setup.exe...")
        iss_file = APP_DIR / "installer.iss"
        if iss_file.exists():
            res_iscc = subprocess.run([iscc, str(iss_file)], cwd=str(APP_DIR))
            if res_iscc.returncode == 0:
                setup_path = APP_DIR / "setup_output" / f"Urahara_Setup_v{ver}.exe"
                print(f"   🎉 Instalador criado com sucesso: {setup_path}")
                setup_created = True
            else:
                print("   ⚠️ Inno Setup retornou erro. Gerando pacote portátil ZIP...")
    else:
        print("   ℹ️ Inno Setup não está instalado no sistema.")
        print("   (Para gerar o Urahara_Setup.exe automaticamente, instale o Inno Setup gratuito em: https://jrsoftware.org/isdl.php)")

    # 3. Create Portable Release ZIP
    print("\n[3/3] Criando pacote portátil Urahara_Portable.zip...")
    out_dir = APP_DIR / "setup_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"Urahara_v{ver}_Portable.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, "Urahara.exe")
        zf.write(APP_DIR / "app_icon.ico", "app_icon.ico")
        zf.write(APP_DIR / "app_icon.png", "app_icon.png")
        zf.write(APP_DIR / "version.json", "version.json")
        zf.write(APP_DIR / ".env.example", ".env.example")
        if (APP_DIR / "README.md").exists():
            zf.write(APP_DIR / "README.md", "README.md")
        # Include realcugan models
        cugan_dir = APP_DIR / "bin" / "realcugan"
        if cugan_dir.exists():
            for root, _, files in os.walk(cugan_dir):
                for f in files:
                    fp = Path(root) / f
                    rel = fp.relative_to(APP_DIR)
                    zf.write(fp, str(rel))

    print(f"✓ Pacote portátil criado: {zip_path}")
    print("\n" + "=" * 60)
    print(" 🎉 PROCESSO CONCLUÍDO!")
    if setup_created:
        print(f" 1. Instalador: setup_output/Urahara_Setup_v{ver}.exe")
    print(f" 2. Executável Portátil: dist/Urahara.exe (Sem terminal)")
    print(f" 3. Pacote para Release: setup_output/Urahara_v{ver}_Portable.zip")
    print("=" * 60)


if __name__ == "__main__":
    main()
