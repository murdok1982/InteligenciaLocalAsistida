REGION_MAP = {
    'US': 'Norteamérica', 'CA': 'Norteamérica', 'MX': 'América Latina',
    'BR': 'América Latina', 'AR': 'América Latina', 'CL': 'América Latina',
    'GB': 'Europa Occidental', 'FR': 'Europa Occidental', 'DE': 'Europa Occidental',
    'RU': 'Europa del Este', 'UA': 'Europa del Este',
    'CN': 'Asia Oriental', 'JP': 'Asia Oriental', 'KR': 'Asia Oriental',
    'IN': 'Asia del Sur', 'PK': 'Asia del Sur',
    'SA': 'Oriente Medio', 'EG': 'Oriente Medio', 'IL': 'Oriente Medio',
    'TR': 'Oriente Medio', 'IR': 'Oriente Medio',
    'ZA': 'África Subsahariana', 'NG': 'África Subsahariana',
    'ET': 'África Subsahariana', 'KE': 'África Subsahariana',
    'AU': 'Oceanía', 'NZ': 'Oceanía',
}

def region_for(code: str) -> str:
    return REGION_MAP.get(code, "Desconocida")
