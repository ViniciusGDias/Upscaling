"""
windows_notifier.py - Notificações Nativas do Windows para o Urahara Studio.
Exibe notificações Toast nativas do Windows 10/11 de forma 100% assíncrona,
sem travar a interface e sem requerer pacotes externos compilados em C.
"""

import sys
import threading
import subprocess


def show_toast(title: str, message: str, sound: bool = True):
    """
    Exibe uma notificação Toast nativa do Windows em thread separada.
    """
    if sys.platform != "win32":
        return

    def _worker():
        try:
            # Escapa aspas para evitar injeção de script no PowerShell
            clean_title = title.replace('"', '""').replace("'", "''")
            clean_msg = message.replace('"', '""').replace("'", "''")

            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName('text')
            $textNodes.Item(0).AppendChild($template.CreateTextNode('{clean_title}')) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode('{clean_msg}')) > $null
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Urahara Studio')
            $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier.Show($notification)
            """

            # Se o Windows.UI.Notifications falhar em versões antigas, usa o balão de sistema como fallback
            fallback_ps = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $global:balloon = New-Object System.Windows.Forms.NotifyIcon
            $path = (Get-Process -id $pid).Path
            $balloon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($path)
            $balloon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
            $balloon.BalloonTipText = '{clean_msg}'
            $balloon.BalloonTipTitle = '{clean_title}'
            $balloon.Visible = $true
            $balloon.ShowBalloonTip(5000)
            """

            # Executa com windowstyle hidden sem criar janela de console
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
            res = subprocess.run(cmd, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            if res.returncode != 0:
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", fallback_ps],
                               startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()
