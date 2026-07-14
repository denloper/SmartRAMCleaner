"""
Модуль автообновления через GitHub Releases.
Проверяет последнюю версию и скачивает новый .exe
"""
import os
import sys
import json
import requests
import subprocess
import tempfile
import shutil
from datetime import datetime
from PyQt5.QtWidgets import QMessageBox, QProgressDialog, QApplication
from PyQt5.QtCore import Qt

# Импортируем константы из основного файла
try:
    from smart_ram_cleaner import APP_VERSION, APP_NAME, GITHUB_REPO
except ImportError:
    APP_VERSION = "1.0.0"
    APP_NAME = "Smart RAM Cleaner Pro"
    GITHUB_REPO = "DENLOPER/SmartRAMCleaner"


def is_frozen():
    """Проверяет, запущено ли приложение как скомпилированный .exe"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_current_exe_path():
    """Возвращает путь к текущему .exe файлу"""
    if is_frozen():
        return sys.executable
    return os.path.abspath(sys.argv[0])


def compare_versions(v1, v2):
    """
    Сравнивает версии в формате X.Y.Z
    Возвращает: 1 если v1 > v2, -1 если v1 < v2, 0 если равны
    """
    def parse(v):
        # Убираем префикс 'v' если есть
        v = v.lstrip('v').split('-')[0]  # убираем '-beta' и подобное
        parts = []
        for p in v.split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return parts
    
    p1, p2 = parse(v1), parse(v2)
    for a, b in zip(p1, p2):
        if a > b: return 1
        if a < b: return -1
    return 0


def check_for_updates(parent_widget=None, silent=False):
    """
    Проверяет наличие обновлений на GitHub.
    
    Args:
        parent_widget: родительское окно для диалогов
        silent: если True, не показывает сообщений когда обновлений нет
    
    Returns:
        dict с информацией об обновлении или None
    """
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        headers = {'Accept': 'application/vnd.github.v3+json'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 404:
            if not silent:
                QMessageBox.information(
                    parent_widget, "Обновления",
                    "Релизы не найдены.\nУбедитесь, что в репозитории есть хотя бы один Release."
                )
            return None
        
        if response.status_code != 200:
            if not silent:
                QMessageBox.warning(
                    parent_widget, "Ошибка",
                    f"Не удалось проверить обновления.\nКод: {response.status_code}"
                )
            return None
        
        data = response.json()
        latest_version = data.get('tag_name', '').lstrip('v')
        current_version = APP_VERSION.lstrip('v')
        
        # Сравниваем версии
        if compare_versions(latest_version, current_version) <= 0:
            if not silent:
                QMessageBox.information(
                    parent_widget, "Обновления",
                    f"✅ У вас установлена последняя версия!\n\n"
                    f"Текущая: v{current_version}\n"
                    f"Последняя: v{latest_version}"
                )
            return None
        
        # Нашли обновление!
        # Ищем .exe файл в ассетах релиза
        exe_asset = None
        for asset in data.get('assets', []):
            if asset['name'].lower().endswith('.exe'):
                exe_asset = asset
                break
        
        if not exe_asset:
            QMessageBox.warning(
                parent_widget, "Ошибка",
                "В релизе не найден .exe файл для скачивания."
            )
            return None
        
        return {
            'version': latest_version,
            'current_version': current_version,
            'download_url': exe_asset['browser_download_url'],
            'filename': exe_asset['name'],
            'size_mb': exe_asset['size'] / (1024 * 1024),
            'changelog': data.get('body', 'Список изменений не указан.'),
            'published_at': data.get('published_at', ''),
            'html_url': data.get('html_url', '')
        }
        
    except requests.exceptions.Timeout:
        if not silent:
            QMessageBox.warning(parent_widget, "Ошибка", "Превышено время ожидания.\nПроверьте интернет-соединение.")
        return None
    except requests.exceptions.ConnectionError:
        if not silent:
            QMessageBox.warning(parent_widget, "Ошибка", "Нет подключения к интернету.")
        return None
    except Exception as e:
        if not silent:
            QMessageBox.warning(parent_widget, "Ошибка", f"Ошибка проверки обновлений:\n{e}")
        return None


def show_update_dialog(update_info, parent_widget=None):
    """Показывает диалог с информацией об обновлении"""
    msg = QMessageBox(parent_widget)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle("🎉 Доступно обновление!")
    
    changelog = update_info['changelog']
    if len(changelog) > 500:
        changelog = changelog[:500] + "..."
    
    msg.setText(
        f"<h3>Доступна новая версия!</h3>"
        f"<p><b>Текущая:</b> v{update_info['current_version']}</p>"
        f"<p><b>Новая:</b> v{update_info['version']}</p>"
        f"<p><b>Размер:</b> {update_info['size_mb']:.1f} МБ</p>"
        f"<hr>"
        f"<p><b>📋 Что нового:</b></p>"
        f"<pre style='background:#f0f0f0; padding:10px; max-height:200px; overflow:auto;'>{changelog}</pre>"
    )
    msg.setTextFormat(Qt.RichText)
    
    download_btn = msg.addButton("📥 Скачать и установить", QMessageBox.AcceptRole)
    changelog_btn = msg.addButton("🌐 Открыть на GitHub", QMessageBox.ActionRole)
    msg.addButton("Позже", QMessageBox.RejectRole)
    
    msg.exec_()
    
    clicked = msg.clickedButton()
    if clicked == download_btn:
        return "download"
    elif clicked == changelog_btn:
        import webbrowser
        webbrowser.open(update_info['html_url'])
        return "github"
    return "later"


def download_and_install(update_info, parent_widget=None):
    """Скачивает новый .exe и запускает установку"""
    try:
        # Создаём прогресс-диалог
        progress = QProgressDialog(
            f"Скачивание {update_info['filename']}...", 
            "Отмена", 0, 100, parent_widget
        )
        progress.setWindowTitle("Обновление")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        # Путь для сохранения
        current_exe = get_current_exe_path()
        current_dir = os.path.dirname(current_exe)
        temp_dir = tempfile.gettempdir()
        download_path = os.path.join(temp_dir, f"SmartRAMCleaner_update_{update_info['version']}.exe")
        
        # Скачиваем с прогрессом
        response = requests.get(update_info['download_url'], stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if progress.wasCanceled():
                    f.close()
                    os.remove(download_path)
                    return False
                
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        progress.setValue(percent)
                        progress.setLabelText(
                            f"Скачивание {update_info['filename']}...\n"
                            f"{downloaded / (1024*1024):.1f} / {total_size / (1024*1024):.1f} МБ"
                        )
                        QApplication.processEvents()
        
        progress.close()
        
        # === УСТАНОВКА ОБНОВЛЕНИЯ ===
        # Создаём bat-скрипт, который:
        # 1. Ждёт закрытия текущего процесса
        # 2. Заменяет старый .exe на новый
        # 3. Запускает новую версию
        # 4. Удаляет себя
        
        current_pid = os.getpid()
        updater_bat = os.path.join(temp_dir, "smart_ram_updater.bat")
        
        bat_content = f"""@echo off
chcp 65001 >nul
echo.
echo ═══════════════════════════════════════
echo   Smart RAM Cleaner - Обновление...
echo ═══════════════════════════════════════
echo.

echo [1/4] Ожидание закрытия приложения...
:wait_loop
tasklist /FI "PID eq {current_pid}" 2>NUL | find "{current_pid}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)

echo [2/4] Создание резервной копии...
if exist "{current_exe}.backup" del "{current_exe}.backup"
copy "{current_exe}" "{current_exe}.backup" >NUL

echo [3/4] Установка новой версии...
copy /y "{download_path}" "{current_exe}" >NUL

echo [4/4] Запуск новой версии...
start "" "{current_exe}"

echo.
echo ✅ Обновление успешно установлено!
echo.

del "{download_path}"
del "%~f0"
"""
        
        with open(updater_bat, 'w', encoding='utf-8') as f:
            f.write(bat_content)
        
        # Показываем финальное сообщение
        reply = QMessageBox.question(
            parent_widget,
            "Готово к установке",
            f"✅ Версия v{update_info['version']} скачана!\n\n"
            f"Для установки приложение будет закрыто и перезапущено.\n"
            f"Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            # Запускаем bat-скрипт и закрываем приложение
            subprocess.Popen(
                [updater_bat],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True
            )
            # Выходим из приложения
            QApplication.quit()
            sys.exit(0)
        else:
            # Пользователь отказался — удаляем временные файлы
            try:
                os.remove(download_path)
                os.remove(updater_bat)
            except:
                pass
        
        return True
        
    except requests.exceptions.RequestException as e:
        QMessageBox.critical(parent_widget, "Ошибка", f"Ошибка скачивания:\n{e}")
        return False
    except Exception as e:
        QMessageBox.critical(parent_widget, "Ошибка", f"Непредвиденная ошибка:\n{e}")
        return False


def check_updates_on_startup(parent_widget=None):
    """Тихая проверка обновлений при запуске"""
    update_info = check_for_updates(parent_widget, silent=True)
    if update_info:
        # Проверяем, не откладывал ли пользователь это обновление
        skip_file = os.path.join(tempfile.gettempdir(), f"skip_update_{update_info['version']}.txt")
        if os.path.exists(skip_file):
            return
        
        result = show_update_dialog(update_info, parent_widget)
        if result == "download":
            download_and_install(update_info, parent_widget)