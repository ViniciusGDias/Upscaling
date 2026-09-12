import PyInstaller.__main__
import os
import customtkinter

# Get customtkinter path for assets
ctk_path = os.path.dirname(customtkinter.__file__)

PyInstaller.__main__.run([
    'app.py',
    '--name=Urahara',
    '--noconsole',
    '--onefile',
    '--icon=app_icon.ico',
    '--add-data=upscaler.py;.',
    '--add-data=audio_separator.py;.',
    '--add-data=audio_tab.py;.',
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
    '--hidden-import=demucs',
    '--hidden-import=torch',
    '--hidden-import=torchaudio',
    '--clean',
])

