import PyInstaller.__main__
import os
import customtkinter

# Get customtkinter path for assets
ctk_path = os.path.dirname(customtkinter.__file__)

PyInstaller.__main__.run([
    'app.py',
    '--name=Urahara',
    '--noconsole',
    '--onedir',
    '--icon=app_icon.ico',
    '--add-data=upscaler.py;.',
    '--add-data=ai_upscaler.py;.',
    '--add-data=isolate_vocals_demucs.py;.',
    '--add-data=audio_separator.py;.',
    '--add-data=audio_tab.py;.',
    '--add-data=refiner_tab.py;.',
    '--add-data=refiner_mastercut.py;.',
    '--add-data=api_health_manager.py;.',
    '--add-data=director_tab.py;.',
    '--add-data=director_ai.py;.',
    '--add-data=instagram_tab.py;.',
    '--add-data=yt_shorts_tab.py;.',
    '--add-data=social_analyzer.py;.',
    '--add-data=anime_finder_tab.py;.',
    '--add-data=anime_finder_ai.py;.',
    '--add-data=metadata_enricher.py;.',
    '--add-data=settings_tab.py;.',
    '--add-data=settings_manager.py;.',
    '--add-data=engine_manager.py;.',
    '--add-data=updater.py;.',
    '--add-data=update_dialog.py;.',
    '--add-data=version.json;.',
    '--add-data=style_analyzer.py;.',
    '--add-data=subtitle_renderer.py;.',
    '--add-data=subtitle_corrector.py;.',
    '--add-data=subtitle_editor_dialog.py;.',
    '--add-data=censorship_manager.py;.',
    '--add-data=censorship_editor_dialog.py;.',
    '--add-data=studio_tab.py;.',
    '--add-data=video_trimmer.py;.',
    '--add-data=ai_cache_hub.py;.',
    '--add-data=dataset_logger.py;.',
    '--add-data=icon_manager.py;.',
    '--add-data=sidebar_navigation.py;.',
    '--add-data=windows_notifier.py;.',
    '--add-data=video_preview_player.py;.',
    '--add-data=batch_history_tab.py;.',
    '--add-data=subtitle_preview_helper.py;.',
    '--add-data=urahara_theme.json;.',
    '--add-data=user_style.json;.' if __import__('os').path.exists('user_style.json') else '--add-data=version.json;.',
    '--add-data=anime_dictionary.json;.' if __import__('os').path.exists('anime_dictionary.json') else '--add-data=version.json;.',
    '--add-data=.env.example;.',
    '--add-data=anime_fx_analyzer.py;.',
    '--add-data=manga_fx_engine.py;.',
    '--add-data=emoji_text_renderer.py;.',
    '--add-data=gemini_web_automator.py;.',
    '--add-data=urahara_theme.py;.',
    '--add-data=thumbnail_studio.py;.',
    '--add-data=haarcascade_frontalface_default.xml;.' if __import__('os').path.exists('haarcascade_frontalface_default.xml') else '--add-data=version.json;.',
    '--add-data=assets;assets' if __import__('os').path.exists('assets') else '--add-data=version.json;.',
    '--add-data=app_icon.ico;.',
    '--add-data=app_icon.png;.',
    f'--add-data={ctk_path};customtkinter/',
    '--hidden-import=windnd',
    '--hidden-import=soundfile',
    '--hidden-import=pygame',
    '--hidden-import=dataset_logger',
    '--hidden-import=emoji',
    '--hidden-import=playwright',
    '--hidden-import=requests',
    '--exclude-module=torch',
    '--exclude-module=torchvision',
    '--exclude-module=torchaudio',
    '--exclude-module=demucs',
    '--exclude-module=basicsr',
    '--exclude-module=realesrgan',
    '--noconfirm',
    '--clean',
])

# Post-build copy of runtime configurations (SEGURANÇA: NUNCA COPIAR .env REAL!)
import shutil
from pathlib import Path
dist_dir = Path("dist/Urahara")
if dist_dir.exists():
    # Garante que nenhum .env com chaves privadas vazadas seja incluído no build
    leaked_env = dist_dir / ".env"
    if leaked_env.exists():
        try:
            leaked_env.unlink()
            print("🔒 [SEGURANÇA] Arquivo .env com chaves privadas removido da pasta dist.")
        except Exception:
            pass

    for f in [
        ".env.example", "user_style.json", "anime_dictionary.json", "urahara_theme.json",
        "urahara_theme.py", "emoji_text_renderer.py", "thumbnail_studio.py",
        "anime_fx_analyzer.py", "manga_fx_engine.py", "gemini_web_automator.py",
        "haarcascade_frontalface_default.xml",
        "sidebar_navigation.py", "icon_manager.py", "subtitle_preview_helper.py",
        "subtitle_editor_dialog.py", "subtitle_renderer.py", "censorship_manager.py",
        "censorship_editor_dialog.py", "custom_profanity.json", "studio_tab.py",
        "ai_cache_hub.py", "dataset_logger.py", "social_analyzer.py", "yt_shorts_tab.py", "instagram_tab.py",
        "batch_history_tab.py", "video_preview_player.py", "windows_notifier.py",
        "refiner_tab.py", "refiner_mastercut.py", "updater.py", "update_dialog.py", "settings_tab.py",
        "director_tab.py", "director_ai.py", "metadata_enricher.py",
        "anime_finder_tab.py", "anime_finder_ai.py"
    ]:
        p = Path(f)
        if p.exists():
            shutil.copy(p, dist_dir / f)
            internal_dir = dist_dir / "_internal"
            if internal_dir.exists():
                shutil.copy(p, internal_dir / f)
            print(f"Copied {f} to {dist_dir}")
    if Path("assets").exists():
        dist_assets = dist_dir / "assets"
        shutil.copytree("assets", dist_assets, dirs_exist_ok=True)
        print(f"Copied assets to {dist_assets}")


