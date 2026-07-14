# Сохрани как paged_leak_detector.py и запусти ОТ ИМЕНИ АДМИНИСТРАТОРА
import ctypes
import urllib.request
import logging
import os
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("PagedLeakDetector")

SystemPoolTagInformation = 0x16
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

class SYSTEM_POOLTAG(ctypes.Structure):
    _fields_ = [
        ("Tag", ctypes.c_ubyte * 4),
        ("PagedAllocs", ctypes.c_uint32),
        ("PagedFrees", ctypes.c_uint32),
        ("_pad1", ctypes.c_uint32),
        ("PagedUsed", ctypes.c_uint64),
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
    """Запрос к ядру Windows: получаем ВСЕ теги памяти"""
    ntdll = ctypes.WinDLL('ntdll')
    ntdll.NtQuerySystemInformation.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
    ]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_long

    buf_size = 0x100000
    buffer = ctypes.create_string_buffer(buf_size)
    ret_len = ctypes.c_uint32()
    
    status = ntdll.NtQuerySystemInformation(
        SystemPoolTagInformation, buffer, buf_size, ctypes.byref(ret_len)
    )
    
    if status == STATUS_INFO_LENGTH_MISMATCH:
        buf_size = ret_len.value
        buffer = ctypes.create_string_buffer(buf_size)
        status = ntdll.NtQuerySystemInformation(
            SystemPoolTagInformation, buffer, buf_size, ctypes.byref(ret_len)
        )
        
    if status != 0:
        logger.error(f"Ядро отказало (код: {hex(status)}). Запустите от Админа!")
        return []

    header = SYSTEM_POOLTAG_INFORMATION.from_buffer(buffer)
    tags = []
    tag_size = ctypes.sizeof(SYSTEM_POOLTAG)
    
    for i in range(header.Count):
        offset = ctypes.sizeof(SYSTEM_POOLTAG_INFORMATION) + i * tag_size
        tag_info = SYSTEM_POOLTAG.from_buffer(buffer, offset)
        
        try:
            tag_str = bytes(tag_info.Tag).decode('ascii', errors='ignore').strip()
            tag_str = "".join(c for c in tag_str if 32 <= ord(c) < 127).ljust(4, '.')
        except:
            tag_str = "????"
            
        # Берём ИМЕННО PagedUsed (выгружаемый пул), а не NonPagedUsed
        if tag_info.PagedUsed > 0:
            tags.append({
                'tag': tag_str,
                'paged_used': tag_info.PagedUsed
            })
            
    tags.sort(key=lambda x: x['paged_used'], reverse=True)
    return tags

def get_driver_mapping():
    """База тегов драйверов"""
    url = "https://raw.githubusercontent.com/zodiacon/PoolMonXv2/master/PoolMonX/res/pooltag.txt"
    filename = "pooltag.txt"
    if not os.path.exists(filename):
        logger.info("Скачивание базы тегов...")
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
        logger.error(f"Ошибка базы: {e}")
    return mapping

def get_product_name(sys_filename):
    """Читает производителя драйвера"""
    cmd = f'powershell -Command "(Get-Command C:\\Windows\\System32\\drivers\\{sys_filename} -ErrorAction SilentlyContinue).FileVersionInfo.ProductName"'
    try:
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=3)
        return result.strip() or "Неизвестно"
    except: return "Неизвестно"

def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        logger.warning("⚠️ Запустите ОТ ИМЕНИ АДМИНИСТРАТОРА!")

    logger.info("Анализ ВЫГРУЖАЕМОГО пула (Paged Pool)...")
    tags = get_pool_tags()
    if not tags: return

    mapping = get_driver_mapping()
    top_mb = tags[0]['paged_used'] / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("🔥 АНАЛИЗ ВЫГРУЖАЕМОГО ПУЛА (Paged Pool)")
    logger.info("=" * 60)
    logger.info("ТОП-10 самых прожорливых тегов:")
    
    for i, t in enumerate(tags[:10]):
        mb = t['paged_used'] / (1024 * 1024)
        driver = mapping.get(t['tag'], "Неизвестный компонент")
        logger.info(f"{i+1:2}. Тег: [{t['tag']}] | {mb:7.1f} МБ | {driver}")
        
    if top_mb > 50:
        driver_name = mapping.get(tags[0]['tag'])
        desc = get_product_name(driver_name) if driver_name and driver_name.endswith('.sys') else driver_name
        
        logger.info("\n" + "=" * 60)
        logger.info("🎯 НАЙДЕН ВИНОВНИК УТЕЧКИ ВЫГРУЖАЕМОГО ПУЛА!")
        logger.info(f"Тег: {tags[0]['tag']} | Память: {top_mb:.1f} МБ")
        logger.info(f"Файл: {driver_name} | Производитель: {desc}")
        logger.info("=" * 60)
        
        # Рекомендации
        if "tcp" in str(driver_name).lower() or "afd" in str(tags[0]['tag']).lower():
            logger.info("💡 Это TCP/IP стек. Частая причина: антивирус или фаервол.")
        elif "net" in str(driver_name).lower() or "ndis" in str(driver_name).lower():
            logger.info("💡 Это сетевой драйвер. Обновите драйвер сетевой карты.")
        elif "ntfs" in str(driver_name).lower():
            logger.info("💡 Это NTFS драйвер. Возможно, проблема с правами доступа к файлам.")
        elif "fltmgr" in str(driver_name).lower() or tags[0]['tag'] == 'FMfn':
            logger.info("💡 Это Filter Manager. Обычно виноват антивирус (Kaspersky, ESET, Avast).")

if __name__ == "__main__":
    main()
    input("\nНажмите Enter для выхода...")