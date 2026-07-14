import sys
import os
import json
import time
import ctypes
import psutil
import webbrowser
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
                             QCheckBox, QTabWidget, QTextEdit, QGroupBox,
                             QProgressBar, QMessageBox, QSystemTrayIcon,
                             QMenu, QAction, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QIcon, QColor, QPixmap, QPainter, QPen, QFontMetrics

# ==================== ВЕРСИЯ ПРИЛОЖЕНИЯ ====================
APP_VERSION = "1.0.0"
APP_NAME = "Smart RAM Cleaner Pro"
GITHUB_REPO = "ТВОЙ_НИК/SmartRAMCleaner"  # ← Замени на свой!
# Например: "coolhacker123/SmartRAMCleaner"

# ==================== КОНСТАНТЫ WINDOWS API ====================
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008

SystemMemoryListInformation = 80
SystemFileCacheInformation = 21
SystemCombinePhysicalMemoryInformation = 130

MemoryPurgeLowPriorityStandbyList = 0
MemoryPurgeNormalPriorityStandbyList = 1
MemoryPurgeHighPriorityStandbyList = 2
MemoryPurgeModifiedList = 3
MemoryPurgeStandbyList = 4
MemoryPurgeUnusedPages = 5

# ==================== ПРОВЕРКА ПРАВ ====================
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    try:
        exe_path = os.path.abspath(sys.argv[0])
        params = ' '.join(sys.argv[1:])
        if exe_path.endswith('.py'):
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{exe_path}" {params}', None, 1)
        else:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe_path, params, None, 1)
        if ret > 32:
            sys.exit(0)
    except Exception as e:
        print(f"Ошибка запроса прав: {e}")

# ==================== СТРУКТУРЫ WINDOWS ====================
class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
        ("HandleCount", ctypes.c_ulong), ("ProcessCount", ctypes.c_ulong),
        ("ThreadCount", ctypes.c_ulong),
    ]

class MEMORY_COMBINE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Handle", ctypes.c_void_p),
        ("SetPad", ctypes.c_uint64),
        ("CombineCondition", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
    ]

class SYSTEM_CACHE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("CurrentSize", ctypes.c_size_t),
        ("PeakSize", ctypes.c_size_t),
        ("PageFaultCount", ctypes.c_uint32),
        ("MinimumWorkingSet", ctypes.c_size_t),
        ("MaximumWorkingSet", ctypes.c_size_t),
        ("CurrentSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("PeakSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("TransitionRePurposeCount", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
    ]

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", ctypes.c_uint32)]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", ctypes.c_uint32), 
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]

# ==================== НАСТРОЙКИ ====================
DEFAULT_CONFIG = {
    "ram_threshold_percent": 85,
    "commit_critical_percent": 85,
    "check_interval_sec": 0.5,
    "cooldown_sec": 300,
    "min_process_memory_mb": 300,
    "max_disk_write_mb_s": 10.0,
    "autostart": False,
    "start_minimized": False,
    "require_admin": True,
    "clean_working_set": True,
    "clean_standby_low": False,
    "clean_standby_normal": False,
    "clean_standby_all": False,
    "clean_system_cache": False,
    "clean_combine_lists": False,
    "clean_modified_list": False,
    "clean_paged_pool": False,
    "clean_priority_boost": False,
    "clean_trim_processes": False,
    "clean_transition_pages": False,
    "whitelist": [
        "explorer.exe", "svchost.exe", "csrss.exe", "dwm.exe", 
        "System", "searchui.exe", "shellexperiencehost.exe",
        "services.exe", "lsass.exe", "wininit.exe"
    ],
    "user_whitelist": []
}

CLEANING_METHODS = [
    {"key": "clean_working_set", "name": "Working Set", 
     "description": "Переводит неактивные данные в Standby List",
     "safety": "safe", "icon": "🟢", "warning": None},
    {"key": "clean_standby_low", "name": "Standby Low",
     "description": "Низкоприоритетный резерв",
     "safety": "safe", "icon": "🟢", "warning": None},
    {"key": "clean_standby_normal", "name": "Standby Normal",
     "description": "Резерв нормального приоритета",
     "safety": "safe", "icon": "🟢", "warning": None},
    {"key": "clean_standby_all", "name": "Standby All",
     "description": "Весь резерв памяти",
     "safety": "moderate", "icon": "🟡",
     "warning": "Кратковременные замедления"},
    {"key": "clean_system_cache", "name": "System Cache",
     "description": "Кэш файлов",
     "safety": "moderate", "icon": "🟡",
     "warning": "Замедлит открытие программ"},
    {"key": "clean_combine_lists", "name": "Combine Lists",
     "description": "Объединение дублей памяти",
     "safety": "moderate", "icon": "🟡",
     "warning": "Микро-фризы"},
    {"key": "clean_paged_pool", "name": "Paged Pool",
     "description": "Выгружаемый пул ядра",
     "safety": "risky", "icon": "🟠",
     "warning": "Может дестабилизировать систему!"},
    {"key": "clean_priority_boost", "name": "Priority Boost",
     "description": "Сброс приоритетов",
     "safety": "safe", "icon": "🟢", "warning": None},
    {"key": "clean_trim_processes", "name": "Trim All",
     "description": "Обрезка всех процессов",
     "safety": "moderate", "icon": "🟡",
     "warning": "Агрессивный метод"},
    {"key": "clean_transition_pages", "name": "Transition Pages",
     "description": "Переходные страницы",
     "safety": "safe", "icon": "🟢", "warning": None},
    {"key": "clean_modified_list", "name": "Modified List",
     "description": "Запись изменённых страниц на диск",
     "safety": "dangerous", "icon": "🔴",
     "warning": "ВРЕДИТ SSD!"},
]

def enable_privilege(privilege_name):
    try:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        token = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            ctypes.byref(token)):
            return False
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
            kernel32.CloseHandle(token)
            return False
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        kernel32.CloseHandle(token)
        return True
    except:
        return False

# ==================== ОСНОВНОЙ ПОТОК МОНИТОРИНГА ====================
class CleanerThread(QThread):
    log_signal = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
        self.last_clean_time = 0
        self.last_disk_time = time.time()
        self.last_disk_io = psutil.disk_io_counters()
        
        enable_privilege("SeProfileSingleProcessPrivilege")
        enable_privilege("SeIncreaseQuotaPrivilege")
        enable_privilege("SeDebugPrivilege")
        
    def safe_sleep(self, seconds):
        end_time = time.time() + seconds
        while time.time() < end_time:
            if not self.running:
                return
            time.sleep(0.01)
        
    def get_deep_stats(self):
        try:
            psapi = ctypes.windll.psapi
            perf_info = PERFORMANCE_INFORMATION()
            perf_info.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
            if psapi.GetPerformanceInfo(ctypes.byref(perf_info), perf_info.cb):
                ps = perf_info.PageSize
                return {
                    "commit_total_gb": (perf_info.CommitTotal * ps) / (1024**3),
                    "commit_limit_gb": (perf_info.CommitLimit * ps) / (1024**3),
                    "kernel_nonpaged_mb": (perf_info.KernelNonpaged * ps) / (1024**2),
                    "kernel_paged_mb": (perf_info.KernelPaged * ps) / (1024**2),
                    "system_cache_mb": (perf_info.SystemCache * ps) / (1024**2)
                }
        except:
            pass
        return None
        
    def empty_working_set(self, pid):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
            if handle:
                ctypes.windll.psapi.EmptyWorkingSet(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except:
            pass
        return False
        
    def clean_memory_list(self, command):
        try:
            ntdll = ctypes.windll.ntdll
            cmd = ctypes.c_uint32(command)
            status = ntdll.NtSetSystemInformation(
                SystemMemoryListInformation,
                ctypes.byref(cmd), ctypes.sizeof(cmd))
            return status == 0
        except:
            return False
            
    def clean_system_cache(self):
        try:
            ntdll = ctypes.windll.ntdll
            cache_info = SYSTEM_CACHE_INFORMATION()
            status = ntdll.NtQuerySystemInformation(
                SystemFileCacheInformation,
                ctypes.byref(cache_info), ctypes.sizeof(cache_info), None)
            if status == 0:
                cache_info.MinimumWorkingSet = ctypes.c_size_t(-1).value
                status = ntdll.NtSetSystemInformation(
                    SystemFileCacheInformation,
                    ctypes.byref(cache_info), ctypes.sizeof(cache_info))
                return status == 0
        except:
            pass
        return False
        
    def clean_combine_lists(self):
        try:
            ntdll = ctypes.windll.ntdll
            combine_info = MEMORY_COMBINE_INFORMATION()
            combine_info.SetPad = 0
            combine_info.CombineCondition = 0
            combine_info.Flags = 0
            status = ntdll.NtSetSystemInformation(
                SystemCombinePhysicalMemoryInformation,
                ctypes.byref(combine_info), ctypes.sizeof(combine_info))
            return status == 0
        except:
            return False
        
    def get_active_pids(self):
        active = set()
        try:
            procs = list(psutil.process_iter(['pid', 'cpu_percent']))
            count = 0
            for p in procs:
                if count >= 15:
                    break
                try:
                    cpu = p.info['cpu_percent']
                    if cpu and cpu > 2.0:
                        active.add(p.info['pid'])
                        count += 1
                except:
                    continue
        except:
            pass
        return active
        
    def calculate_disk_latency(self, current_io, dt):
        try:
            delta_read_time = current_io.read_time - self.last_disk_io.read_time
            delta_write_time = current_io.write_time - self.last_disk_io.write_time
            delta_read_count = current_io.read_count - self.last_disk_io.read_count
            delta_write_count = current_io.write_count - self.last_disk_io.write_count
            total_ops = delta_read_count + delta_write_count
            total_time = delta_read_time + delta_write_time
            if total_ops > 0:
                return total_time / total_ops
            return 0.0
        except:
            return 0.0
    
    def _get_process_memory(self, pid):
        """Надёжное получение памяти процесса"""
        try:
            proc = psutil.Process(pid)
            return proc.memory_info().rss
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            return 0
        except Exception:
            return 0
    
    def do_clean(self, aggressive=False):
        """Надёжная очистка с детальным логированием"""
        active_pids = self.get_active_pids()
        whitelist = set([p.lower() for p in self.config['whitelist'] + self.config['user_whitelist']])
        min_mem_mb = 50 if aggressive else self.config['min_process_memory_mb']
        
        stats = {
            'total': 0, 'whitelisted': 0, 'active': 0, 'too_small': 0,
            'working_set_cleaned': 0, 'failed': 0, 'no_memory_info': 0,
            'standby_low': False, 'standby_normal': False, 'standby_all': False,
            'system_cache': False, 'combine': False, 'modified': False,
            'paged_pool': False, 'priority_boost': False, 'trim': False, 'transition': False
        }
        details = []
        
        # ДИАГНОСТИКА
        self.log_signal.emit(f"🔍 Поиск процессов для очистки (min={min_mem_mb}МБ)...")
        
        if self.config.get('clean_working_set', True) or aggressive:
            try:
                all_procs = list(psutil.process_iter(['pid', 'name']))
                self.log_signal.emit(f"📋 Всего процессов в системе: {len(all_procs)}")
            except Exception as e:
                self.log_signal.emit(f"❌ Ошибка получения списка: {e}")
                all_procs = []
            
            # Получаем память через отдельные вызовы
            procs_with_mem = []
            for p in all_procs:
                try:
                    pid = p.info['pid']
                    name = p.info['name'] or f"PID_{pid}"
                    rss_bytes = self._get_process_memory(pid)
                    procs_with_mem.append({
                        'pid': pid,
                        'name': name,
                        'rss_bytes': rss_bytes
                    })
                except Exception:
                    continue
            
            mem_ok_count = sum(1 for p in procs_with_mem if p['rss_bytes'] > 0)
            self.log_signal.emit(f"✅ Память получена у: {mem_ok_count} из {len(procs_with_mem)} процессов")
            
            # Сортируем по памяти
            procs_with_mem.sort(key=lambda x: x['rss_bytes'], reverse=True)
            
            # ТОП-5 для диагностики
            if aggressive and procs_with_mem:
                self.log_signal.emit("🏆 ТОП-5 процессов по памяти:")
                for i, p in enumerate(procs_with_mem[:5]):
                    mb = p['rss_bytes'] / (1024**2)
                    self.log_signal.emit(f"   {i+1}. {p['name']} ({mb:.1f} МБ)")
            
            # Основной цикл очистки
            for proc_data in procs_with_mem:
                if not self.running:
                    break
                    
                stats['total'] += 1
                pid = proc_data['pid']
                name = proc_data['name'].lower()
                rss_bytes = proc_data['rss_bytes']
                
                if rss_bytes == 0:
                    stats['no_memory_info'] += 1
                    continue
                
                rss_mb = rss_bytes / (1024**2)
                
                if name in whitelist:
                    stats['whitelisted'] += 1
                    continue
                
                if not aggressive and pid in active_pids:
                    stats['active'] += 1
                    continue
                
                if rss_mb < min_mem_mb:
                    stats['too_small'] += 1
                    continue
                
                if self.empty_working_set(pid):
                    stats['working_set_cleaned'] += 1
                    details.append(f"✅ {name} ({rss_mb:.0f} МБ)")
                else:
                    stats['failed'] += 1
                
                if stats['working_set_cleaned'] >= (20 if aggressive else 10):
                    break
        
        # Системные методы очистки
        if self.config.get('clean_standby_low', False):
            stats['standby_low'] = self.clean_memory_list(MemoryPurgeLowPriorityStandbyList)
        if self.config.get('clean_standby_normal', False):
            stats['standby_normal'] = self.clean_memory_list(MemoryPurgeNormalPriorityStandbyList)
        if self.config.get('clean_standby_all', False):
            stats['standby_all'] = self.clean_memory_list(MemoryPurgeStandbyList)
        if self.config.get('clean_system_cache', False):
            stats['system_cache'] = self.clean_system_cache()
        if self.config.get('clean_combine_lists', False):
            stats['combine'] = self.clean_combine_lists()
        if self.config.get('clean_paged_pool', False):
            stats['paged_pool'] = self.clean_memory_list(MemoryPurgeUnusedPages)
        if self.config.get('clean_priority_boost', False):
            stats['priority_boost'] = self.clean_memory_list(MemoryPurgeUnusedPages)
        if self.config.get('clean_trim_processes', False):
            try:
                for p in psutil.process_iter(['pid']):
                    if not self.running: break
                    try:
                        self.empty_working_set(p.info['pid'])
                    except: continue
                stats['trim'] = True
            except: pass
        if self.config.get('clean_transition_pages', False):
            stats['transition'] = self.clean_memory_list(MemoryPurgeUnusedPages)
        if self.config.get('clean_modified_list', False) and aggressive:
            stats['modified'] = self.clean_memory_list(MemoryPurgeModifiedList)
        
        # Финальная статистика
        self.log_signal.emit(
            f"📈 Итог: найдено {stats['total']} | "
            f"нет памяти {stats['no_memory_info']} | "
            f"whitelist {stats['whitelisted']} | "
            f"активные {stats['active']} | "
            f"мелкие {stats['too_small']} | "
            f"ошибки {stats['failed']}"
        )
                
        return stats, details
        
    def run(self):
        self.log_signal.emit("✅ Очиститель запущен. Обновление каждые 500мс...")
        
        while self.running:
            try:
                mem = psutil.virtual_memory()
                swap = psutil.swap_memory()
                deep_stats = self.get_deep_stats()
                
                current_time = time.time()
                current_io = psutil.disk_io_counters()
                dt = current_time - self.last_disk_time
                
                disk_write_speed = 0
                disk_latency_ms = 0
                if dt > 0:
                    disk_write_speed = (current_io.write_bytes - self.last_disk_io.write_bytes) / dt / (1024**2)
                    disk_latency_ms = self.calculate_disk_latency(current_io, dt)
                
                stats = {
                    "ram_percent": mem.percent,
                    "ram_used_gb": mem.used / (1024**3),
                    "ram_total_gb": mem.total / (1024**3),
                    "swap_percent": swap.percent,
                    "swap_used_gb": swap.used / (1024**3),
                    "swap_total_gb": swap.total / (1024**3),
                    "nonpaged_mb": deep_stats['kernel_nonpaged_mb'] if deep_stats else 0,
                    "paged_mb": deep_stats['kernel_paged_mb'] if deep_stats else 0,
                    "commit_gb": deep_stats['commit_total_gb'] if deep_stats else 0,
                    "commit_limit_gb": deep_stats['commit_limit_gb'] if deep_stats else 0,
                    "system_cache_mb": deep_stats['system_cache_mb'] if deep_stats else 0,
                    "disk_write": disk_write_speed,
                    "disk_latency_ms": disk_latency_ms
                }
                self.stats_updated.emit(stats)
                
                if disk_write_speed > self.config['max_disk_write_mb_s']:
                    self.last_disk_time = current_time
                    self.last_disk_io = current_io
                    self.safe_sleep(self.config['check_interval_sec'])
                    continue
                
                commit_usage = (stats['commit_gb'] / stats['commit_limit_gb'] * 100) if stats['commit_limit_gb'] > 0 else 0
                trigger_ram = self.config['ram_threshold_percent']
                if commit_usage > self.config['commit_critical_percent']:
                    trigger_ram = 60
                    
                time_since_clean = current_time - self.last_clean_time
                if (mem.percent > trigger_ram or commit_usage > 90) and time_since_clean > self.config['cooldown_sec']:
                    self.log_signal.emit(f"⚡ Триггер: RAM {mem.percent:.1f}% | Commit {commit_usage:.1f}%. Запуск очистки...")
                    clean_stats, _ = self.do_clean(aggressive=False)
                    
                    methods = []
                    if clean_stats['working_set_cleaned'] > 0: methods.append(f"WS:{clean_stats['working_set_cleaned']}")
                    if clean_stats['standby_low']: methods.append("SB-L")
                    if clean_stats['standby_normal']: methods.append("SB-N")
                    if clean_stats['standby_all']: methods.append("SB-A")
                    if clean_stats['system_cache']: methods.append("SC")
                    if clean_stats['combine']: methods.append("CB")
                        
                    self.log_signal.emit(
                        f"🧹 Очищено: [{'+'.join(methods)}] | "
                        f"Пропущено: {clean_stats['whitelisted']} (wl), "
                        f"{clean_stats['active']} (cpu), "
                        f"{clean_stats['too_small']} (small)"
                    )
                    self.last_clean_time = current_time
                    
            except Exception as e:
                if self.running:
                    self.log_signal.emit(f"❌ Ошибка: {e}")
                
            self.last_disk_time = current_time
            self.last_disk_io = current_io
            self.safe_sleep(self.config['check_interval_sec'])
            
    def stop(self):
        self.running = False


# ==================== WORKER ДЛЯ ФОНОВОЙ ОЧИСТКИ ====================
class CleanWorker(QObject):
    """Worker для выполнения очистки в отдельном потоке"""
    finished = pyqtSignal(dict, list)
    log_signal = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
    
    def do_work(self):
        """Выполняет очистку и возвращает результаты"""
        try:
            self.log_signal.emit("🔍 Анализ процессов...")
            temp_thread = CleanerThread(self.config)
            self.log_signal.emit("🧹 Запуск очистки...")
            clean_stats, details = temp_thread.do_clean(aggressive=True)
            self.log_signal.emit("✅ Очистка завершена")
            self.finished.emit(clean_stats, details)
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка: {e}")
            self.finished.emit(None, [])


# ==================== ГЛАВНОЕ ОКНО ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.cleaner_thread = None
        
        # Кэши
        self._last_tray_percent = -1
        self._tray_icon_cache = {}
        self._latest_stats = None
        self._cleaning_in_progress = False
        self.clean_worker_thread = None
        self.clean_worker = None
        
        self.ext_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_extension')
        self.setup_chrome_extension()
        self.init_ui()
        self.setup_tray()
        self.start_cleaner()
        
        # QTimer для обновления UI каждые 500мс
        self.ui_update_timer = QTimer()
        self.ui_update_timer.setInterval(500)
        self.ui_update_timer.timeout.connect(self._update_ui_from_cache)
        self.ui_update_timer.start()
    
    def setup_chrome_extension(self):
        """Автоматически создаёт файлы расширения Chrome"""
        os.makedirs(self.ext_dir, exist_ok=True)
        
        manifest = {
            "manifest_version": 3,
            "name": "Smart Tab Suspender",
            "version": "1.1",
            "description": "Замораживает неактивные вкладки. Ctrl+Shift+S = мгновенная заморозка.",
            "permissions": ["tabs", "storage", "alarms", "activeTab", "contextMenus"],
            "host_permissions": ["<all_urls>"],
            "background": {"service_worker": "background.js"},
            "action": {"default_popup": "popup.html"},
            "options_page": "options.html",
            "commands": {
                "freeze-current": {
                    "suggested_key": {"default": "Ctrl+Shift+S"},
                    "description": "Заморозить текущую вкладку"
                },
                "freeze-all": {
                    "suggested_key": {"default": "Ctrl+Shift+A"},
                    "description": "Заморозить все неактивные"
                }
            }
        }
        
        manifest_path = os.path.join(self.ext_dir, 'manifest.json')
        if not os.path.exists(manifest_path):
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        background_js = """const DEFAULT_SETTINGS = {
  enabled: true, suspendTime: 10,
  whitelist: ['youtube.com', 'music.youtube.com', 'spotify.com', 'twitch.tv', 'discord.com'],
  dontSuspendPinned: true, dontSuspendAudio: true, dontSuspendActive: true
};
let lastAccessedTime = {};
let suspendCount = 0;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({id: 'freeze-tab', title: '❄️ Заморозить эту вкладку', contexts: ['page']});
  chrome.contextMenus.create({id: 'freeze-all', title: '⚡ Заморозить все', contexts: ['page']});
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'freeze-tab' && tab) await freezeTab(tab.id);
  else if (info.menuItemId === 'freeze-all') await suspendAll();
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'freeze-current') {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await freezeTab(tab.id);
  } else if (command === 'freeze-all') await suspendAll();
});

chrome.tabs.onActivated.addListener(info => { lastAccessedTime[info.tabId] = Date.now(); });
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'complete') lastAccessedTime[tabId] = Date.now();
});
chrome.tabs.onRemoved.addListener(tabId => { delete lastAccessedTime[tabId]; });

chrome.alarms.create('checkTabs', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'checkTabs') checkAndSuspend();
});

async function freezeTab(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.discarded) return { success: false, reason: 'already_frozen' };
    if (tab.audible) return { success: false, reason: 'audio_playing' };
    if (tab.url.startsWith('chrome')) return { success: false, reason: 'system_page' };
    await chrome.tabs.discard(tabId);
    suspendCount++;
    return { success: true };
  } catch (e) {
    return { success: false, reason: e.message };
  }
}

async function checkAndSuspend() {
  const data = await chrome.storage.local.get(DEFAULT_SETTINGS);
  const settings = { ...DEFAULT_SETTINGS, ...data };
  if (!settings.enabled) return;
  const tabs = await chrome.tabs.query({});
  const now = Date.now();
  for (const tab of tabs) {
    if (tab.discarded) continue;
    if (!tab.url || tab.url.startsWith('chrome')) continue;
    if (tab.active && settings.dontSuspendActive) continue;
    if (tab.pinned && settings.dontSuspendPinned) continue;
    if (tab.audible && settings.dontSuspendAudio) continue;
    try {
      const url = new URL(tab.url);
      if (settings.whitelist.some(d => url.hostname.includes(d))) continue;
    } catch(e) { continue; }
    const lastAccess = lastAccessedTime[tab.id] || tab.lastAccessed || now;
    const inactiveMinutes = (now - lastAccess) / 1000 / 60;
    if (inactiveMinutes > settings.suspendTime) {
      try { await chrome.tabs.discard(tab.id); suspendCount++; } catch(e) {}
    }
  }
}

async function suspendAll() {
  const tabs = await chrome.tabs.query({});
  let count = 0;
  for (const tab of tabs) {
    if (!tab.discarded && !tab.active && !tab.audible) {
      try { await chrome.tabs.discard(tab.id); suspendCount++; count++; } catch(e) {}
    }
  }
  return count;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'GET_STATS') sendResponse({ suspendCount });
  else if (request.type === 'SUSPEND_NOW') freezeTab(request.tabId).then(sendResponse);
  else if (request.type === 'SUSPEND_ALL') suspendAll().then(count => sendResponse({ success: true, count }));
  else if (request.type === 'SUSPEND_CURRENT') {
    chrome.tabs.query({ active: true, currentWindow: true }, async ([tab]) => {
      if (tab) sendResponse(await freezeTab(tab.id));
      else sendResponse({ success: false, reason: 'no_active_tab' });
    });
  }
  return true;
});"""
        
        bg_path = os.path.join(self.ext_dir, 'background.js')
        if not os.path.exists(bg_path):
            with open(bg_path, 'w', encoding='utf-8') as f:
                f.write(background_js)
        
        popup_html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body { width: 340px; font-family: 'Segoe UI', Arial; background: #1e1e1e; color: white; padding: 15px; margin: 0; }
h3 { margin: 0 0 15px; color: #007acc; }
.stats { background: #252526; padding: 12px; border-radius: 5px; margin-bottom: 10px; }
.stat-num { font-size: 28px; font-weight: bold; color: #007acc; }
button { background: #007acc; color: white; border: none; padding: 10px 12px; border-radius: 4px; cursor: pointer; width: 100%; margin-top: 5px; font-weight: bold; }
button:hover { background: #005a9e; }
button.primary { background: #e74c3c; }
button.primary:hover { background: #c0392b; }
button.secondary { background: #3c3c3c; }
.toggle { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #333; }
.switch { position: relative; width: 40px; height: 20px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: #444; border-radius: 20px; transition: .3s; }
.slider:before { position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: .3s; }
input:checked + .slider { background: #007acc; }
input:checked + .slider:before { transform: translateX(20px); }
.hotkeys { font-size: 10px; color: #888; margin-top: 10px; padding: 8px; background: #252526; border-radius: 3px; }
.kbd { background: #3c3c3c; padding: 2px 6px; border-radius: 3px; border: 1px solid #555; font-family: monospace; }
.status { padding: 8px; border-radius: 3px; margin-top: 8px; text-align: center; font-weight: bold; display: none; }
.status.success { background: #27ae60; display: block; }
.status.error { background: #e74c3c; display: block; }
</style></head>
<body>
<h3>🧠 Smart Tab Suspender</h3>
<div class="stats"><div>Заморожено вкладок:</div><div class="stat-num" id="statsCount">0</div></div>
<button id="freezeCurrentBtn" class="primary">❄️ Заморозить ТЕКУЩУЮ вкладку</button>
<button id="suspendAllBtn">⚡ Заморозить все неактивные</button>
<div id="statusMsg" class="status"></div>
<div class="toggle"><span>Автозаморозка</span>
<label class="switch"><input type="checkbox" id="enabledToggle" checked><span class="slider"></span></label></div>
<button id="settingsBtn" class="secondary">⚙️ Настройки</button>
<div class="hotkeys">
<b>⌨️ Горячие клавиши:</b><br>
<span class="kbd">Ctrl</span>+<span class="kbd">Shift</span>+<span class="kbd">S</span> — текущую<br>
<span class="kbd">Ctrl</span>+<span class="kbd">Shift</span>+<span class="kbd">A</span> — все<br>
<b>🖱️ ПКМ на вкладке</b> — меню
</div>
<script src="popup.js"></script>
</body></html>"""
        
        popup_path = os.path.join(self.ext_dir, 'popup.html')
        if not os.path.exists(popup_path):
            with open(popup_path, 'w', encoding='utf-8') as f:
                f.write(popup_html)
        
        popup_js = """document.addEventListener('DOMContentLoaded', async () => {
  const data = await chrome.storage.local.get(['enabled']);
  document.getElementById('enabledToggle').checked = data.enabled !== false;
  chrome.runtime.sendMessage({ type: 'GET_STATS' }, response => {
    document.getElementById('statsCount').textContent = response?.suspendCount || 0;
  });
  const statusEl = document.getElementById('statusMsg');
  function showStatus(text, isError = false) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (isError ? 'error' : 'success');
    setTimeout(() => statusEl.className = 'status', 2500);
  }
  document.getElementById('enabledToggle').addEventListener('change', async (e) => {
    await chrome.storage.local.set({ enabled: e.target.checked });
  });
  document.getElementById('freezeCurrentBtn').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'SUSPEND_CURRENT' }, response => {
      if (response?.success) showStatus('✅ Вкладка заморожена!');
      else {
        const reasons = {'already_frozen':'Уже заморожена','audio_playing':'Звук','system_page':'Системная','no_active_tab':'Нет вкладки'};
        showStatus('⚠️ ' + (reasons[response?.reason] || 'Ошибка'), true);
      }
    });
  });
  document.getElementById('suspendAllBtn').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'SUSPEND_ALL' }, response => {
      if (response?.success) {
        showStatus(`✅ Заморожено: ${response.count}`);
        chrome.runtime.sendMessage({ type: 'GET_STATS' }, r => {
          document.getElementById('statsCount').textContent = r?.suspendCount || 0;
        });
      }
    });
  });
  document.getElementById('settingsBtn').addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
});"""
        
        popup_js_path = os.path.join(self.ext_dir, 'popup.js')
        if not os.path.exists(popup_js_path):
            with open(popup_js_path, 'w', encoding='utf-8') as f:
                f.write(popup_js)
        
        options_html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Настройки</title>
<style>
body { font-family: 'Segoe UI', Arial; background: #1e1e1e; color: white; padding: 20px; max-width: 600px; margin: 0 auto; }
h2 { color: #007acc; }
.section { background: #252526; padding: 15px; border-radius: 5px; margin-bottom: 15px; }
label { display: block; margin: 10px 0 5px; }
input[type="number"], textarea { background: #3c3c3c; color: white; border: 1px solid #555; padding: 8px; border-radius: 3px; width: 100%; box-sizing: border-box; }
textarea { height: 100px; font-family: monospace; }
button { background: #007acc; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: bold; }
.checkbox-row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
</style></head>
<body>
<h2>⚙️ Настройки</h2>
<div class="section"><h3>⏱️ Время до заморозки</h3>
<label>Минут неактивности:</label>
<input type="number" id="suspendTime" min="1" max="1440" value="10"></div>
<div class="section"><h3>🛡️ Исключения</h3>
<div class="checkbox-row"><input type="checkbox" id="dontSuspendPinned" checked><label>Закреплённые</label></div>
<div class="checkbox-row"><input type="checkbox" id="dontSuspendAudio" checked><label>Со звуком</label></div>
<div class="checkbox-row"><input type="checkbox" id="dontSuspendActive" checked><label>Активную</label></div></div>
<div class="section"><h3>🌐 Белый список</h3>
<label>Домены:</label><textarea id="whitelist"></textarea></div>
<button id="saveBtn">💾 Сохранить</button>
<span id="status" style="margin-left: 10px; color: #27ae60;"></span>
<script src="options.js"></script>
</body></html>"""
        
        options_path = os.path.join(self.ext_dir, 'options.html')
        if not os.path.exists(options_path):
            with open(options_path, 'w', encoding='utf-8') as f:
                f.write(options_html)
        
        options_js = """document.addEventListener('DOMContentLoaded', async () => {
  const data = await chrome.storage.local.get({
    suspendTime: 10,
    whitelist: ['youtube.com', 'music.youtube.com', 'spotify.com', 'twitch.tv', 'discord.com'],
    dontSuspendPinned: true, dontSuspendAudio: true, dontSuspendActive: true
  });
  document.getElementById('suspendTime').value = data.suspendTime;
  document.getElementById('whitelist').value = data.whitelist.join('\\n');
  document.getElementById('dontSuspendPinned').checked = data.dontSuspendPinned;
  document.getElementById('dontSuspendAudio').checked = data.dontSuspendAudio;
  document.getElementById('dontSuspendActive').checked = data.dontSuspendActive;
  document.getElementById('saveBtn').addEventListener('click', async () => {
    await chrome.storage.local.set({
      suspendTime: parseInt(document.getElementById('suspendTime').value) || 10,
      whitelist: document.getElementById('whitelist').value.split('\\n').map(s => s.trim()).filter(s => s),
      dontSuspendPinned: document.getElementById('dontSuspendPinned').checked,
      dontSuspendAudio: document.getElementById('dontSuspendAudio').checked,
      dontSuspendActive: document.getElementById('dontSuspendActive').checked
    });
    document.getElementById('status').textContent = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').textContent = '', 2000);
  });
});"""
        
        options_js_path = os.path.join(self.ext_dir, 'options.js')
        if not os.path.exists(options_js_path):
            with open(options_js_path, 'w', encoding='utf-8') as f:
                f.write(options_js)
    
    def init_ui(self):
        self.setWindowTitle("Smart RAM Cleaner Pro")
        self.setGeometry(100, 100, 900, 750)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QWidget { background-color: #1e1e1e; color: #ffffff; }
            QTabWidget::pane { border: 1px solid #333333; background-color: #252526; }
            QTabBar::tab { background-color: #2d2d30; color: #cccccc; padding: 8px 16px; border: 1px solid #333333; }
            QTabBar::tab:selected { background-color: #007acc; color: white; }
            QGroupBox { border: 1px solid #333333; border-radius: 5px; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #007acc; }
            QPushButton { background-color: #007acc; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #005a9e; }
            QPushButton:disabled { background-color: #444444; }
            QLineEdit, QSpinBox, QDoubleSpinBox { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 5px; border-radius: 3px; }
            QTextEdit { background-color: #1e1e1e; color: #cccccc; border: 1px solid #333333; font-family: 'Consolas', monospace; }
            QProgressBar { border: 1px solid #333333; border-radius: 3px; text-align: center; background-color: #2d2d30; min-height: 20px; }
            QProgressBar::chunk { background-color: #007acc; }
            QCheckBox { color: #cccccc; spacing: 8px; }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        title = QLabel("🧠 Smart RAM Cleaner Pro")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #007acc; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        self.admin_status = QLabel()
        self.admin_status.setAlignment(Qt.AlignCenter)
        if is_admin():
            self.admin_status.setText("🛡️ Запущено с правами администратора")
            self.admin_status.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
        else:
            self.admin_status.setText("⚠️ Нет прав администратора")
            self.admin_status.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 5px; background: #3a1a1a; border-radius: 3px;")
        main_layout.addWidget(self.admin_status)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self.create_monitoring_tab()
        self.create_cleaning_tab()
        self.create_settings_tab()
        self.create_whitelist_tab()
        self.create_chrome_tab()
        self.create_build_tab()
        self.create_log_tab()
    
    def create_monitoring_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        ram_group = QGroupBox("📊 Оперативная память")
        ram_layout = QVBoxLayout()
        self.ram_label = QLabel("Загрузка: 0%")
        self.ram_label.setFont(QFont("Segoe UI", 12))
        ram_layout.addWidget(self.ram_label)
        self.ram_progress = QProgressBar()
        self.ram_progress.setRange(0, 100)
        self.ram_progress.setFormat("%v%")
        ram_layout.addWidget(self.ram_progress)
        self.ram_details = QLabel("Используется: 0 ГБ / 0 ГБ")
        ram_layout.addWidget(self.ram_details)
        ram_group.setLayout(ram_layout)
        layout.addWidget(ram_group)
        
        swap_group = QGroupBox("💾 Файл подкачки")
        swap_layout = QVBoxLayout()
        self.swap_label = QLabel("Загрузка: 0%")
        self.swap_label.setFont(QFont("Segoe UI", 12))
        swap_layout.addWidget(self.swap_label)
        self.swap_progress = QProgressBar()
        self.swap_progress.setRange(0, 100)
        self.swap_progress.setFormat("%v%")
        swap_layout.addWidget(self.swap_progress)
        self.swap_details = QLabel("Используется: 0 ГБ / 0 ГБ")
        swap_layout.addWidget(self.swap_details)
        swap_group.setLayout(swap_layout)
        layout.addWidget(swap_group)
        
        pools_group = QGroupBox("⚙️ Система и диск")
        pools_layout = QVBoxLayout()
        self.pools_label = QLabel(
            "<b>Невыгружаемый пул:</b> 0 МБ<br>"
            "<b>Выгружаемый пул:</b> 0 МБ<br>"
            "<b>Системный кэш:</b> 0 МБ<br>"
            "<b>Commit:</b> 0 ГБ / 0 ГБ (0%)<br>"
            "<b>Запись:</b> 0.00 МБ/с<br>"
            "<b>Задержка:</b> 0.0 мс"
        )
        self.pools_label.setFont(QFont("Segoe UI", 10))
        pools_layout.addWidget(self.pools_label)
        pools_group.setLayout(pools_layout)
        layout.addWidget(pools_group)
        
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("⏹ Остановить")
        self.start_btn.clicked.connect(self.toggle_cleaner)
        btn_layout.addWidget(self.start_btn)
        self.clean_now_btn = QPushButton("⚡ Очистить сейчас")
        self.clean_now_btn.clicked.connect(self.clean_now)
        btn_layout.addWidget(self.clean_now_btn)
        layout.addLayout(btn_layout)
        layout.addStretch()
        self.tabs.addTab(tab, "📊 Мониторинг")
    
    def create_cleaning_tab(self):
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        desc = QLabel("⚙️ <b>Выберите методы очистки памяти</b>")
        desc.setWordWrap(True)
        desc.setStyleSheet("padding: 10px; background-color: #2d2d30; border-radius: 5px;")
        main_layout.addWidget(desc)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        self.cleaning_checkboxes = {}
        
        for method in CLEANING_METHODS:
            g = QGroupBox(f"{method['icon']} {method['name']}")
            l = QVBoxLayout()
            cb = QCheckBox(method['description'])
            cb.setChecked(self.config.get(method['key'], False))
            
            if method['safety'] == 'dangerous':
                cb.setStyleSheet("color: #e74c3c; font-weight: bold;")
                g.setStyleSheet("QGroupBox { border: 2px solid #e74c3c; }")
            elif method['safety'] == 'risky':
                cb.setStyleSheet("color: #f39c12;")
                g.setStyleSheet("QGroupBox { border: 1px solid #f39c12; }")
            
            l.addWidget(cb)
            self.cleaning_checkboxes[method['key']] = cb
            if method['warning']:
                w = QLabel(f"⚠️ {method['warning']}")
                w.setWordWrap(True)
                w.setStyleSheet("color:#aaa; font-size: 9pt; padding: 5px; background-color: #3a1a1a; border-radius: 3px;")
                l.addWidget(w)
            g.setLayout(l)
            scroll_layout.addWidget(g)
        
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        
        save_btn = QPushButton("💾 Сохранить методы очистки")
        save_btn.clicked.connect(self.save_cleaning_settings)
        main_layout.addWidget(save_btn)
        self.tabs.addTab(tab, "🧹 Методы очистки")
    
    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        group1 = QGroupBox("🎯 Триггеры очистки")
        l1 = QVBoxLayout()
        
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Порог ОЗУ (%):"))
        self.ram_threshold = QSpinBox()
        self.ram_threshold.setRange(50, 99)
        self.ram_threshold.setValue(self.config['ram_threshold_percent'])
        h1.addWidget(self.ram_threshold)
        l1.addLayout(h1)
        
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Критический Commit (%):"))
        self.commit_threshold = QSpinBox()
        self.commit_threshold.setRange(50, 99)
        self.commit_threshold.setValue(self.config['commit_critical_percent'])
        h2.addWidget(self.commit_threshold)
        l1.addLayout(h2)
        
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Интервал обновления (сек):"))
        self.check_interval = QDoubleSpinBox()
        self.check_interval.setRange(0.3, 10.0)
        self.check_interval.setSingleStep(0.1)
        self.check_interval.setDecimals(1)
        self.check_interval.setValue(self.config['check_interval_sec'])
        h3.addWidget(self.check_interval)
        l1.addLayout(h3)
        
        h4 = QHBoxLayout()
        h4.addWidget(QLabel("Задержка между очистками (сек):"))
        self.cooldown = QSpinBox()
        self.cooldown.setRange(60, 3600)
        self.cooldown.setValue(self.config['cooldown_sec'])
        h4.addWidget(self.cooldown)
        l1.addLayout(h4)
        
        group1.setLayout(l1)
        layout.addWidget(group1)
        
        group2 = QGroupBox("🛡️ Защита SSD")
        l2 = QVBoxLayout()
        h5 = QHBoxLayout()
        h5.addWidget(QLabel("Мин. память процесса (МБ):"))
        self.min_mem = QSpinBox()
        self.min_mem.setRange(50, 4096)
        self.min_mem.setValue(self.config['min_process_memory_mb'])
        h5.addWidget(self.min_mem)
        l2.addLayout(h5)
        h6 = QHBoxLayout()
        h6.addWidget(QLabel("Макс. запись на диск (МБ/с):"))
        self.max_disk = QSpinBox()
        self.max_disk.setRange(1, 100)
        self.max_disk.setValue(int(self.config['max_disk_write_mb_s']))
        h6.addWidget(self.max_disk)
        l2.addLayout(h6)
        group2.setLayout(l2)
        layout.addWidget(group2)
        
        group3 = QGroupBox("🚀 Поведение")
        l3 = QVBoxLayout()
        self.autostart_cb = QCheckBox("Запускать вместе с Windows")
        self.autostart_cb.setChecked(self.config['autostart'])
        l3.addWidget(self.autostart_cb)
        self.minimize_cb = QCheckBox("Запускать свёрнутым в трей")
        self.minimize_cb.setChecked(self.config['start_minimized'])
        l3.addWidget(self.minimize_cb)
        self.require_admin_cb = QCheckBox("🛡️ Требовать права администратора")
        self.require_admin_cb.setChecked(self.config.get('require_admin', True))
        self.require_admin_cb.setStyleSheet("color: #f39c12; font-weight: bold;")
        l3.addWidget(self.require_admin_cb)
        group3.setLayout(l3)
        layout.addWidget(group3)
        
        save_btn = QPushButton("💾 Сохранить настройки")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        restart_admin_btn = QPushButton("🔄 Перезапустить от имени администратора")
        restart_admin_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        restart_admin_btn.clicked.connect(lambda: run_as_admin())
        if is_admin():
            restart_admin_btn.setEnabled(False)
            restart_admin_btn.setText("✅ Уже запущено от администратора")
        layout.addWidget(restart_admin_btn)
        
        layout.addStretch()
        self.tabs.addTab(tab, "⚙️ Настройки")
    
    def create_whitelist_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel("💡 Процессы из этого списка НИКОГДА не будут очищаться.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #cccccc; padding: 10px; background-color: #2d2d30; border-radius: 5px;")
        layout.addWidget(info)
        self.whitelist_edit = QTextEdit()
        self.whitelist_edit.setPlaceholderText("chrome.exe\nfirefox.exe\nsteam.exe")
        self.whitelist_edit.setPlainText("\n".join(self.config['user_whitelist']))
        layout.addWidget(self.whitelist_edit)
        save_btn = QPushButton("💾 Сохранить")
        save_btn.clicked.connect(self.save_whitelist)
        layout.addWidget(save_btn)
        self.tabs.addTab(tab, "🛡️ Белый список")
    
    def create_chrome_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("🌐 Chrome Tab Suspender")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #007acc;")
        layout.addWidget(title)
        
        desc = QLabel("Замораживает неактивные вкладки Chrome, освобождая ОЗУ.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #cccccc; padding: 10px; background-color: #2d2d30; border-radius: 5px;")
        layout.addWidget(desc)
        
        features_group = QGroupBox("✨ Возможности")
        features_layout = QVBoxLayout()
        features_text = QLabel(
            "• <b>Автозаморозка</b> через N минут<br>"
            "• <b>Мгновенная заморозка</b> кнопкой<br>"
            "• <b>Ctrl+Shift+S</b> — заморозить текущую<br>"
            "• <b>Ctrl+Shift+A</b> — заморозить все<br>"
            "• <b>ПКМ на вкладке</b> — меню заморозки"
        )
        features_text.setWordWrap(True)
        features_text.setStyleSheet("color: #cccccc; line-height: 1.5;")
        features_layout.addWidget(features_text)
        features_group.setLayout(features_layout)
        layout.addWidget(features_group)
        
        status_group = QGroupBox("📊 Статус")
        status_layout = QVBoxLayout()
        if os.path.exists(os.path.join(self.ext_dir, 'manifest.json')):
            status_text = QLabel("✅ Готово к установке")
            status_text.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            status_text = QLabel("❌ Файлы не найдены")
            status_text.setStyleSheet("color: #e74c3c; font-weight: bold;")
        status_layout.addWidget(status_text)
        path_label = QLabel(f"📁 {self.ext_dir}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color: #888; font-size: 9pt;")
        status_layout.addWidget(path_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        btn_group = QGroupBox("🔧 Управление")
        btn_layout = QVBoxLayout()
        open_folder_btn = QPushButton("📂 Открыть папку")
        open_folder_btn.clicked.connect(lambda: os.startfile(self.ext_dir))
        btn_layout.addWidget(open_folder_btn)
        open_chrome_btn = QPushButton("🌍 Открыть chrome://extensions")
        open_chrome_btn.clicked.connect(lambda: webbrowser.open("chrome://extensions"))
        btn_layout.addWidget(open_chrome_btn)
        btn_group.setLayout(btn_layout)
        layout.addWidget(btn_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, "🌐 Chrome")
    
    def create_build_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        title = QLabel("📦 Сборка в EXE")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #007acc;")
        layout.addWidget(title)
        
        desc = QLabel("Создаёт standalone .exe файл.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #cccccc; padding: 10px; background-color: #2d2d30; border-radius: 5px;")
        layout.addWidget(desc)
        
        status_group = QGroupBox("🔍 Окружение")
        status_layout = QVBoxLayout()
        self.pyinstaller_status = QLabel("Проверка...")
        status_layout.addWidget(self.pyinstaller_status)
        self.script_status = QLabel()
        status_layout.addWidget(self.script_status)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        self.check_build_environment()
        
        install_btn = QPushButton("📥 Установить PyInstaller")
        install_btn.clicked.connect(self.install_pyinstaller)
        layout.addWidget(install_btn)
        
        build_btn = QPushButton("🔨 Собрать EXE")
        build_btn.setStyleSheet("background-color: #27ae60; font-weight: bold; padding: 12px; font-size: 14px;")
        build_btn.clicked.connect(self.build_exe)
        layout.addWidget(build_btn)
        
        bat_btn = QPushButton("📄 Создать build.bat")
        bat_btn.clicked.connect(self.create_bat_file)
        layout.addWidget(bat_btn)
        
        open_dist_btn = QPushButton("📂 Открыть папку dist/")
        open_dist_btn.clicked.connect(self.open_dist_folder)
        layout.addWidget(open_dist_btn)
        
        layout.addStretch()
        self.tabs.addTab(tab, "📦 Сборка")
    
    def check_build_environment(self):
        try:
            import PyInstaller
            self.pyinstaller_status.setText(f"✅ PyInstaller v{PyInstaller.__version__}")
            self.pyinstaller_status.setStyleSheet("color: #27ae60; font-weight: bold;")
        except ImportError:
            self.pyinstaller_status.setText("❌ PyInstaller НЕ установлен")
            self.pyinstaller_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
        script_path = os.path.abspath(sys.argv[0])
        if script_path.endswith('.py'):
            self.script_status.setText(f"✅ Скрипт: {os.path.basename(script_path)}")
            self.script_status.setStyleSheet("color: #27ae60;")
        else:
            self.script_status.setText(f"⚠️ Запущено из EXE")
            self.script_status.setStyleSheet("color: #f39c12;")
    
    def install_pyinstaller(self):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            QMessageBox.information(self, "Готово", "✅ PyInstaller установлен!")
            self.check_build_environment()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
    
    def build_exe(self):
        script_path = os.path.abspath(sys.argv[0])
        if not script_path.endswith('.py'):
            QMessageBox.warning(self, "Ошибка", "Нужен .py файл")
            return
        try:
            import PyInstaller
        except ImportError:
            QMessageBox.warning(self, "Ошибка", "Сначала установите PyInstaller!")
            return
        
        self.add_log("🔨 Сборка EXE...")
        self.tabs.setCurrentIndex(6)
        QApplication.processEvents()
        
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--onefile", "--windowed",
            "--name", "SmartRAMCleaner",
            "--uac-admin",
            script_path
        ]
        
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.add_log(f"[BUILD] {line}")
                    QApplication.processEvents()
            process.wait()
            
            if process.returncode == 0:
                dist_path = os.path.join(os.path.dirname(script_path), 'dist', 'SmartRAMCleaner.exe')
                self.add_log(f"✅ Сборка успешна!")
                QMessageBox.information(self, "Готово!", f"✅ EXE собран!\n{dist_path}")
            else:
                QMessageBox.critical(self, "Ошибка", "Сборка не удалась")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
    
    def create_bat_file(self):
        script_path = os.path.abspath(sys.argv[0])
        bat_path = os.path.join(os.path.dirname(script_path), 'build.bat')
        bat_content = f"""@echo off
chcp 65001 >nul
echo Сборка Smart RAM Cleaner Pro...
python -m pip install pyinstaller >nul 2>&1
python -m PyInstaller --noconfirm --onefile --windowed --name SmartRAMCleaner --uac-admin "{script_path}"
echo Готово! Файл в папке dist\\
pause
"""
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_content)
        QMessageBox.information(self, "Готово", f"✅ {bat_path}")
    
    def open_dist_folder(self):
        dist_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'dist')
        if os.path.exists(dist_path):
            os.startfile(dist_path)
        else:
            QMessageBox.information(self, "Не найдено", "Сначала соберите EXE")
    
    def create_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        clear_btn = QPushButton("🗑️ Очистить лог")
        clear_btn.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_btn)
        self.tabs.addTab(tab, "📜 Логи")
    
    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.update_tray_icon(0)
        self.tray.setToolTip("Smart RAM Cleaner Pro")
        
        menu = QMenu()
        show_action = QAction("Показать", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)
        clean_action = QAction("⚡ Очистить сейчас", self)
        clean_action.triggered.connect(self.clean_now)
        menu.addAction(clean_action)
        menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
    
    def _create_tray_icon(self, ram_percent):
        """Оптимизированный рендер иконки БЕЗ QPainterPath"""
        percent_int = int(ram_percent)
        
        if percent_int in self._tray_icon_cache:
            return self._tray_icon_cache[percent_int]
        
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("transparent"))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        if percent_int > 90:
            bg_color = QColor("#e74c3c")
        elif percent_int > 75:
            bg_color = QColor("#f39c12")
        else:
            bg_color = QColor("#007acc")
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawEllipse(2, 2, 60, 60)
        
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(2, 2, 60, 60)
        
        text = f"{percent_int}"
        font_size = 30 if percent_int < 100 else 26
        font = QFont("Segoe UI Black", font_size, QFont.Black)
        painter.setFont(font)
        
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        text_height = fm.ascent()
        x = (64 - text_width) / 2
        y = (64 + text_height) / 2 - fm.descent() / 2
        
        # Чёрная тень для обводки
        painter.setPen(QColor(0, 0, 0, 220))
        for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1), (0,-1), (0,1), (-1,0), (1,0)]:
            painter.drawText(int(x + dx), int(y + dy), text)
        
        # Белый текст
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(int(x), int(y), text)
        
        painter.end()
        
        final_pixmap = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(final_pixmap)
        
        if len(self._tray_icon_cache) < 101:
            self._tray_icon_cache[percent_int] = icon
            
        return icon
    
    def update_tray_icon(self, ram_percent):
        """Обновляет иконку только если значение изменилось"""
        percent_int = int(ram_percent)
        
        if percent_int == self._last_tray_percent:
            return
        
        self._last_tray_percent = percent_int
        icon = self._create_tray_icon(ram_percent)
        self.tray.setIcon(icon)
        self.tray.setToolTip(
            f"Smart RAM Cleaner Pro\n"
            f"ОЗУ: {ram_percent:.1f}%\n"
            f"СКМ: очистка | ЛКМ: окно | ПКМ: меню"
        )
    
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
        elif reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()
        elif reason == QSystemTrayIcon.MiddleClick:
            self.clean_now()
            self.tray.showMessage(
                "Smart RAM Cleaner",
                "⚡ Очистка запущена!",
                QSystemTrayIcon.Information, 1500
            )
    
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "Smart RAM Cleaner",
            "Свёрнуто в трей. СКМ = очистка.",
            QSystemTrayIcon.Information, 2000
        )
    
    def quit_app(self):
        if self.cleaner_thread and self.cleaner_thread.isRunning():
            self.cleaner_thread.stop()
            self.cleaner_thread.wait(3000)
            if self.cleaner_thread.isRunning():
                self.cleaner_thread.terminate()
        if self.clean_worker_thread and self.clean_worker_thread.isRunning():
            self.clean_worker_thread.quit()
            self.clean_worker_thread.wait(2000)
        QApplication.quit()
    
    def load_config(self):
        if os.path.exists('settings.json'):
            try:
                with open('settings.json', 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    for k, v in DEFAULT_CONFIG.items():
                        if k not in cfg:
                            cfg[k] = v
                    return cfg
            except:
                pass
        return DEFAULT_CONFIG.copy()
    
    def save_config(self):
        with open('settings.json', 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
    
    def save_settings(self):
        self.config['ram_threshold_percent'] = self.ram_threshold.value()
        self.config['commit_critical_percent'] = self.commit_threshold.value()
        self.config['check_interval_sec'] = self.check_interval.value()
        self.config['cooldown_sec'] = self.cooldown.value()
        self.config['min_process_memory_mb'] = self.min_mem.value()
        self.config['max_disk_write_mb_s'] = self.max_disk.value()
        self.config['autostart'] = self.autostart_cb.isChecked()
        self.config['start_minimized'] = self.minimize_cb.isChecked()
        self.config['require_admin'] = self.require_admin_cb.isChecked()
        
        self.handle_autostart(self.config['autostart'])
        self.save_config()
        
        if self.cleaner_thread:
            self.cleaner_thread.config = self.config
        
        QMessageBox.information(self, "Сохранено", "✅ Настройки сохранены!")
    
    def save_cleaning_settings(self):
        dangerous = []
        for method in CLEANING_METHODS:
            if method['safety'] == 'dangerous' and self.cleaning_checkboxes[method['key']].isChecked():
                dangerous.append(method['name'])
        
        if dangerous:
            reply = QMessageBox.warning(
                self, "⚠️ Опасные опции!",
                f"Вы включили:\n{chr(10).join(dangerous)}\n\nВредит SSD. Продолжить?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        for method in CLEANING_METHODS:
            self.config[method['key']] = self.cleaning_checkboxes[method['key']].isChecked()
        
        self.save_config()
        if self.cleaner_thread:
            self.cleaner_thread.config = self.config
        QMessageBox.information(self, "Сохранено", "✅ Методы обновлены!")
    
    def save_whitelist(self):
        text = self.whitelist_edit.toPlainText()
        self.config['user_whitelist'] = [l.strip() for l in text.split('\n') if l.strip()]
        self.save_config()
        if self.cleaner_thread:
            self.cleaner_thread.config = self.config
        QMessageBox.information(self, "Сохранено", "✅ Белый список обновлён!")
    
    def handle_autostart(self, enable):
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                exe_path = os.path.abspath(sys.argv[0])
                if exe_path.endswith('.py'):
                    exe_path = f'"{sys.executable}" "{exe_path}"'
                else:
                    exe_path = f'"{exe_path}"'
                winreg.SetValueEx(key, "SmartRAMCleaner", 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, "SmartRAMCleaner")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Ошибка автозапуска: {e}")
    
    def start_cleaner(self):
        self.cleaner_thread = CleanerThread(self.config)
        self.cleaner_thread.log_signal.connect(self.add_log)
        self.cleaner_thread.stats_updated.connect(self._on_stats_received)
        
        # Предварительная инициализация psutil
        self.add_log("⏳ Инициализация мониторинга процессов...")
        try:
            for p in psutil.process_iter(['cpu_percent']):
                pass
            self.add_log("✅ Мониторинг готов")
        except Exception as e:
            self.add_log(f"⚠️ Предупреждение: {e}")
        
        self.cleaner_thread.start()
        self.start_btn.setText("⏹ Остановить")
    
    def _on_stats_received(self, stats):
        """Поток присылает статистику, сохраняем в кэш"""
        self._latest_stats = stats
    
    def _update_ui_from_cache(self):
        """QTimer обновляет UI из кэша каждые 500мс"""
        if self._latest_stats is None:
            return
        self._apply_stats_to_ui(self._latest_stats)
    
    def _apply_stats_to_ui(self, stats):
        """Обновление UI из кэша"""
        self.update_tray_icon(stats['ram_percent'])
        
        self.ram_progress.setValue(int(stats['ram_percent']))
        self.ram_label.setText(f"Загрузка ОЗУ: {stats['ram_percent']:.1f}%")
        self.ram_details.setText(f"Используется: {stats['ram_used_gb']:.2f} ГБ / {stats['ram_total_gb']:.2f} ГБ")
        
        if stats['ram_percent'] > 90:
            self.ram_progress.setStyleSheet("QProgressBar::chunk { background-color: #e74c3c; }")
        elif stats['ram_percent'] > 75:
            self.ram_progress.setStyleSheet("QProgressBar::chunk { background-color: #f39c12; }")
        else:
            self.ram_progress.setStyleSheet("QProgressBar::chunk { background-color: #007acc; }")
        
        self.swap_progress.setValue(int(stats['swap_percent']))
        self.swap_label.setText(f"Файл подкачки: {stats['swap_percent']:.1f}%")
        self.swap_details.setText(f"Используется: {stats['swap_used_gb']:.2f} ГБ / {stats['swap_total_gb']:.2f} ГБ")
        
        commit_percent = (stats['commit_gb'] / stats['commit_limit_gb'] * 100) if stats['commit_limit_gb'] > 0 else 0
        latency = stats.get('disk_latency_ms', 0)
        
        if latency < 5:
            latency_color = "#27ae60"
        elif latency < 20:
            latency_color = "#f39c12"
        else:
            latency_color = "#e74c3c"
        
        self.pools_label.setText(
            f"<b>Невыгружаемый пул:</b> {stats['nonpaged_mb']:.0f} МБ<br>"
            f"<b>Выгружаемый пул:</b> {stats['paged_mb']:.0f} МБ<br>"
            f"<b>Системный кэш:</b> {stats['system_cache_mb']:.0f} МБ<br>"
            f"<b>Commit:</b> {stats['commit_gb']:.2f} ГБ / {stats['commit_limit_gb']:.2f} ГБ ({commit_percent:.1f}%)<br>"
            f"<b>Запись:</b> {stats['disk_write']:.2f} МБ/с<br>"
            f"<b>Задержка:</b> <span style='color:{latency_color}; font-weight:bold;'>{latency:.2f} мс</span>"
        )
    
    def toggle_cleaner(self):
        if self.cleaner_thread and self.cleaner_thread.isRunning():
            self.start_btn.setEnabled(False)
            self.start_btn.setText("⏳ Остановка...")
            QApplication.processEvents()
            self.cleaner_thread.stop()
            if not self.cleaner_thread.wait(3000):
                self.cleaner_thread.terminate()
                self.cleaner_thread.wait()
            self.start_btn.setText("▶ Запустить")
            self.start_btn.setEnabled(True)
            self.add_log("⏹ Очиститель остановлен.")
        else:
            self.start_cleaner()
    
    def clean_now(self):
        """Оптимизированная ручная очистка в отдельном потоке"""
        if self._cleaning_in_progress:
            self.add_log("⚠️ Очистка уже выполняется, подождите...")
            return
        
        self._cleaning_in_progress = True
        self.clean_now_btn.setEnabled(False)
        self.clean_now_btn.setText("⏳ Очистка...")
        
        self.add_log("⚡ Запуск ручной очистки в фоновом потоке...")
        
        # Создаём worker thread
        self.clean_worker_thread = QThread()
        self.clean_worker = CleanWorker(self.config)
        self.clean_worker.moveToThread(self.clean_worker_thread)
        
        # Подключаем сигналы
        self.clean_worker_thread.started.connect(self.clean_worker.do_work)
        self.clean_worker.finished.connect(self._on_clean_finished)
        self.clean_worker.log_signal.connect(self.add_log)
        self.clean_worker.finished.connect(self.clean_worker_thread.quit)
        self.clean_worker.finished.connect(self.clean_worker.deleteLater)
        self.clean_worker_thread.finished.connect(self.clean_worker_thread.deleteLater)
        
        self.clean_worker_thread.start()
    
    def _on_clean_finished(self, clean_stats, details):
        """Обработка результатов очистки"""
        self._cleaning_in_progress = False
        self.clean_now_btn.setEnabled(True)
        self.clean_now_btn.setText("⚡ Очистить сейчас")
        
        if clean_stats is None:
            self.add_log("❌ Очистка завершилась с ошибкой")
            return
        
        self.add_log("📊 Результаты очистки:")
        
        names = {
            'working_set_cleaned': ('Working Set', 'процессов'),
            'standby_low': ('Standby Low', ''),
            'standby_normal': ('Standby Normal', ''),
            'standby_all': ('Standby All', ''),
            'system_cache': ('System Cache', ''),
            'combine': ('Combine Lists', ''),
            'modified': ('Modified List', ''),
            'paged_pool': ('Paged Pool', ''),
            'priority_boost': ('Priority Boost', ''),
            'trim': ('Trim All', ''),
            'transition': ('Transition Pages', '')
        }
        
        cleaned_methods = []
        for key, (name, unit) in names.items():
            val = clean_stats.get(key)
            if isinstance(val, bool) and val:
                cleaned_methods.append(f"✅ {name}")
            elif isinstance(val, int) and val > 0:
                cleaned_methods.append(f"✅ {name}: {val} {unit}")
        
        if cleaned_methods:
            for method in cleaned_methods:
                self.add_log(f"   {method}")
        else:
            self.add_log("   ⚠️ Ничего не очищено")
            self.add_log(f"   Причины:")
            self.add_log(f"   • В белом списке: {clean_stats.get('whitelisted', 0)}")
            self.add_log(f"   • Активные (CPU): {clean_stats.get('active', 0)}")
            self.add_log(f"   • Слишком мелкие: {clean_stats.get('too_small', 0)}")
            self.add_log(f"   • Ошибки доступа: {clean_stats.get('failed', 0)}")
            self.add_log(f"   • Нет данных памяти: {clean_stats.get('no_memory_info', 0)}")
        
        if details:
            self.add_log(f"🧹 Детали ({len(details)} процессов):")
            for d in details[:10]:
                self.add_log(f"   {d}")
            if len(details) > 10:
                self.add_log(f"   ... и ещё {len(details) - 10}")
    
    def add_log(self, message):
        """Добавляет сообщение в лог"""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {message}")
        # Автоскролл вниз
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ==================== ТОЧКА ВХОДА ====================
if __name__ == "__main__":
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    if not is_admin():
        early_app = QApplication(sys.argv)
        require_admin = True
        if os.path.exists('settings.json'):
            try:
                with open('settings.json', 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    require_admin = cfg.get('require_admin', True)
            except:
                pass
        
        if require_admin:
            reply = QMessageBox.question(
                None,
                "Права администратора",
                "Для полноценной работы нужны права администратора.\n\nПерезапустить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                run_as_admin()
        del early_app
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    window = MainWindow()
    
    if window.config.get('start_minimized'):
        window.hide()
    else:
        window.show()
    
    sys.exit(app.exec_())