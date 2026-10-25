"""Detección Linux de solo lectura y estimación orientativa de memoria."""
from i18n import tr
from pathlib import Path
import csv
import re
import subprocess

GIB = 1024 ** 3


def command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=6, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def number(path):
    try: return int(path.read_text().strip(), 0)
    except (OSError, ValueError): return None


def vulkan_devices(text):
    result = {}
    for block in re.split(r'GPU\d+:', text)[1:]:
        fields = dict(re.findall(r'^\s*(vendorID|deviceID|deviceType|deviceName)\s*=\s*(.+)$', block, re.M))
        try: result[(int(fields['vendorID'], 0), int(fields['deviceID'], 0))] = fields
        except (KeyError, ValueError): pass
    return result


def detect():
    memory = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value = line.split(':',1)
            memory[key] = int(value.split()[0]) * 1024
    except (OSError, ValueError): pass
    gpus = []
    output = command(['nvidia-smi','--query-gpu=name,memory.total,memory.free','--format=csv,noheader,nounits'])
    for row in csv.reader(output.splitlines()):
        try:
            name,total,free = [x.strip() for x in row]
            gpus.append(dict(name=name, vendor='NVIDIA', total=int(total)*1024**2,
                             free=int(free)*1024**2, dedicated=True))
        except (ValueError, TypeError): pass
    cards = list(Path('/sys/class/drm').glob('card[0-9]*'))
    devices = vulkan_devices(command(['vulkaninfo','--summary'])) if any((c/'device/vendor').exists() for c in cards if number(c/'device/vendor') in (0x1002,0x8086)) else {}
    seen = set()
    for card in cards:
        if not re.fullmatch(r'card\d+',card.name): continue
        dev = card/'device'
        identity = str(dev.resolve())
        if identity in seen: continue
        seen.add(identity)
        vendor,device = number(dev/'vendor'),number(dev/'device')
        if vendor not in (0x1002,0x8086,0x10de): continue
        if vendor==0x10de and any(g['vendor']=='NVIDIA' for g in gpus): continue
        brand={0x1002:'AMD',0x8086:'Intel',0x10de:'NVIDIA'}[vendor]
        vk=devices.get((vendor,device),{})
        dedicated=vk.get('deviceType')=='PHYSICAL_DEVICE_TYPE_DISCRETE_GPU'
        total=number(dev/'mem_info_vram_total') if dedicated else None
        used=number(dev/'mem_info_vram_used') if dedicated else None
        free=max(0,total-used) if total is not None and used is not None else None
        gpus.append(dict(name=vk.get('deviceName',f'{brand} ({card.name})'),vendor=brand,
                         total=total,free=free,dedicated=dedicated))
    return dict(ram=memory.get('MemTotal'), available=memory.get('MemAvailable'),gpus=gpus)


def quantization(name):
    m=re.search(r'(?:^|[-_.])((?:IQ|Q)(\d+)[A-Za-z0-9_]*|BF16|F16|F32|FP16|FP32)(?=$|[-.])',name,re.I)
    if not m:return None
    return int(m.group(2)) if m.group(2) else (32 if '32' in m.group(1) else 16)


def recommend(files, hardware, context, preference=1):
    # El margen es heurístico: sin metadatos de arquitectura no se conoce la caché KV real.
    overhead=2*GIB + context*256*1024
    ram=hardware.get('available') or 0
    gpu=max((g.get('free') or 0 for g in hardware.get('gpus',[]) if g.get('dedicated')),default=0)
    ram_budget=max(0,ram-overhead)
    gpu_budget=max(0,gpu-overhead)
    candidates=[(i,f,quantization(f['file'])) for i,f in enumerate(files) if f.get('size',0)>0 and quantization(f['file']) is not None]
    if not candidates or not ram:
        return None,tr('No pudimos estimar una variante: faltan datos de memoria o cuantización.')
    # No se suman RAM y VRAM ni las memorias de varias GPU.
    fast=[x for x in candidates if x[1]['size']<=gpu_budget and x[1]['size']<=ram_budget]
    fits=fast if fast and preference!=2 else [x for x in candidates if x[1]['size']<=ram_budget]
    if not fits:return None,tr('Ninguna variante entra en el presupuesto estimado de memoria. Puedes elegir manualmente, pero podría no cargar.')
    if preference==0:
        decent=[x for x in fits if x[2]>=4]
        chosen=min(decent or fits,key=lambda x:x[1]['size'])
    elif preference==2:
        chosen=max(fits,key=lambda x:(x[2],x[1]['size']))
    else:
        chosen=min(fits,key=lambda x:(abs(x[2]-4), 'nomtp' in x[1]['file'].lower(), -x[1]['size']))
    i,f,bits=chosen
    route=tr('Cabe en el presupuesto estimado de VRAM y RAM.') if f['size']<=gpu_budget else tr('Estimación basada en RAM: puede usar CPU o carga parcial en GPU y ser más lenta.')
    warning=tr(' La cuantización es baja; puede perder calidad.') if bits<4 else ''
    return i,tr('{0} Reservamos {1:.1f} GiB orientativos para ejecución y contexto ({2:,} tokens).{3} No es una garantía: la arquitectura y la caché real pueden necesitar más memoria.').format(route, overhead / GIB, context, warning)


def summary(h):
    ram=h.get('available')
    lines=[tr('RAM disponible: {0:.1f} GiB').format(ram / GIB) if ram else tr('RAM disponible: sin confirmar')]
    for g in h.get('gpus',[]):
        free=g.get('free')
        lines.append(g['name']+(tr(' · VRAM libre: {0:.1f} GiB').format(free / GIB) if free is not None else tr(' · memoria compartida o VRAM libre sin confirmar')))
    if not h.get('gpus'):lines.append(tr('Sin GPU detectada; estimación basada en RAM.'))
    lines.append(tr('Detectar una GPU no garantiza que el programa que ejecuta el modelo pueda utilizarla. No sumamos memorias compartidas ni varias GPU.'))
    return '\n'.join(lines)
