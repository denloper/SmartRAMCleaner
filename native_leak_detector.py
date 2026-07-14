import ctypes
import urllib.request
import logging
import os
import subprocess
import sys

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("NativeLeakDetector")

# Константы Native Windows API
SystemPoolTagInformation = 0x16
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

# Структуры ядра Windows (с жестким выравниванием для 64-битной ОС)
class SYSTEM_POOLTAG(ctypes.Structure):
    _fields_ = [
        ("Tag", ctypes.c_ubyte * 4),
        ("PagedAllocs", ctypes.c_uint32),
        ("PagedFrees", ctypes.c_uint32),
        ("_pad1", ctypes.c_uint32),       # Padding для выравнивания
        ("PagedUsed", ctypes.c_uint64),   # ULONG_PTR (8 байт на x64)
        ("NonPagedAllocs", ctypes.c_uint32),
        ("NonPagedFrees", ctypes.c_uint32),
        ("NonPagedUsed", ctypes.c_uint64),
    ]

class SYSTEM_POOLTAG_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Count", ctypes.c_uint32),
        ("_pad2", ctypes.c_uint32)
    ]

def get_pool_tags():
    """Делает прямой запрос в ядро Windows за списком всех тегов памяти"""
    ntdll = ctypes.WinDLL('ntdll')
    ntdll.NtQuerySystemInformation.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
    ]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_long

    buf_size = 0x100000  # Начальный буфер 1 МБ
    buffer = ctypes.create_string_buffer(buf_size)
    ret_len = ctypes.c_uint32()
    
    status = ntdll.NtQuerySystemInformation(
        SystemPoolTagInformation, buffer, buf_size, ctypes.byref(ret_len)
    )
    
    # Если буфер мал, ядро вернет нужный размер
    if status == STATUS_INFO_LENGTH_MISMATCH:
        buf_size = ret_len.value
        buffer = ctypes.create_string_buffer(buf_size)
        status = ntdll.NtQuerySystemInformation(
            SystemPoolTagInformation, buffer, buf_size, ctypes.byref(ret_len)
        )
        
    if status != 0:
        logger.error(f"Ядро отказало в доступе (Код: {hex(status)}). Запустите скрипт от имени Администратора!")
        return []

    header = SYSTEM_POOLTAG_INFORMATION.from_buffer(buffer)
    tags = []
    tag_size = ctypes.sizeof(SYSTEM_POOLTAG)
    
    for i in range(header.Count):
        offset = ctypes.sizeof(SYSTEM_POOLTAG_INFORMATION) + i * tag_size
        tag_info = SYSTEM_POOLTAG.from_buffer(buffer, offset)
        
        # Декодируем 4-байтовый тег из ASCII
        try:
            tag_str = bytes(tag_info.Tag).decode('ascii', errors='ignore').strip()
            tag_str = "".join(c for c in tag_str if 32 <= ord(c) < 127).ljust(4, '.')
        except:
            tag_str = "????"
            
        if tag_info.NonPagedUsed > 0:
            tags.append({
                'tag': tag_str,
                'nonpaged_used': tag_info.NonPagedUsed
            })
            
    # Сортируем от самого прожорливого к меньшему
    tags.sort(key=lambda x: x['nonpaged_used'], reverse=True)
    return tags

def get_driver_mapping():
    """Скачивает официальную базу Microsoft (pooltag.txt) для расшифровки тегов"""
    url = "https://raw.githubusercontent.com/zodiacon/PoolMonXv2/master/PoolMonX/res/pooltag.txt"
    filename = "pooltag.txt"
    if not os.path.exists(filename):
        logger.info("Скачивание базы тегов драйверов (pooltag.txt)...")
        try: urllib.request.urlretrieve(url, filename)
        except: return {}
        
    mapping = {}
    try:
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('rem'): continue
                if ' - ' in line:
                    parts = line.split(' - ', 2)
                    mapping[parts[0].strip()] = parts[1].strip()
    except Exception as e:
        logger.error(f"Ошибка чтения базы: {e}")
    return mapping

def get_product_name(sys_filename):
    """Читает метаданные .sys файла, чтобы узнать производителя (NVIDIA, Realtek и т.д.)"""
    cmd = f'powershell -Command "(Get-Command C:\\Windows\\System32\\drivers\\{sys_filename} -ErrorAction SilentlyContinue).FileVersionInfo.ProductName"'
    try:
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=3)
        return result.strip() or "Неизвестно"
    except: return "Неизвестно"

def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        logger.warning("⚠️ ВНИМАНИЕ: Для точного анализа драйверов запустите скрипт ОТ ИМЕНИ АДМИНИСТРАТОРА.")

    logger.info("Инициализация прямого запроса к ядру Windows (Native API)...")
    tags = get_pool_tags()
    if not tags: return

    mapping = get_driver_mapping()
    top_mb = tags[0]['nonpaged_used'] / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("🔥 АНАЛИЗ НЕВЫГРУЖАЕМОГО ПУЛА (Native API)")
    logger.info("=" * 60)
    logger.info("ТОП-5 самых прожорливых тегов ядра:")
    
    for i, t in enumerate(tags[:5]):
        mb = t['nonpaged_used'] / (1024 * 1024)
        driver = mapping.get(t['tag'], "Неизвестный компонент")
        logger.info(f"{i+1}. Тег: [{t['tag']}] | Размер: {mb:.1f} МБ | Файл: {driver}")
        
    if top_mb > 50: # Считаем утечкой всё, что больше 50 МБ на один тег
        driver_name = mapping.get(tags[0]['tag'])
        desc = get_product_name(driver_name) if driver_name and driver_name.endswith('.sys') else driver_name
        
        logger.info("\n" + "=" * 60)
        logger.info("🎯 НАЙДЕН ГЛАВНЫЙ ВИНОВНИК УТЕЧКИ ПАМЯТИ!")
        logger.info(f"Тег: {tags[0]['tag']} | Память: {top_mb:.1f} МБ")
        logger.info(f"Имя файла: {driver_name} | Производитель: {desc}")
        logger.info("=" * 60)
        
        if "ndis" in str(driver_name).lower() or "net" in str(driver_name).lower() or "wifi" in str(desc).lower():
            logger.info("💡 РЕШЕНИЕ: Это утечка сетевого драйвера. Обновите драйвер сетевой карты (Realtek/Killer/Intel) с сайта производителя материнской платы.")
        elif "nv" in str(driver_name).lower() or "nvidia" in str(desc).lower():
            logger.info("💡 РЕШЕНИЕ: Это компонент NVIDIA. Отключите 'NVIDIA Network Service' в службах (services.msc) или обновите драйвер.")
        elif "rtk" in str(driver_name).lower() or "realtek" in str(desc).lower():
            logger.info("💡 РЕШЕНИЕ: Утечка в драйвере Realtek (аудио или сеть). Обновите его через Диспетчер устройств.")
        else:
            logger.info(f"💡 РЕШЕНИЕ: Обновите или переустановите программу/драйвер, связанный с {desc}.")

if __name__ == "__main__":
    main()