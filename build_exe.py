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
    '--add-data=version.json;.',
    '--add-data=app_icon.ico;.',
    '--add-data=app_icon.png;.',
    f'--add-data={ctk_path};customtkinter/',
    '--hidden-import=windnd',
    '--hidden-import=soundfile',
    '--exclude-module=torch',
    '--exclude-module=torchvision',
    '--exclude-module=torchaudio',
    '--exclude-module=demucs',
    '--exclude-module=basicsr',
    '--exclude-module=realesrgan',
    '--noconfirm',
    '--clean',
])

