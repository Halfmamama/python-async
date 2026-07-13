def parse_accounts(raw: str, defaults: list) -> list:
    """
    Парсит ввод аккаунтов.

    Форматы:
        ""      → дефолтные аккаунты
        "*"     → все дефолтные
        "1,3,5" → acc_1, acc_3, acc_5
        "1-5"   → acc_1 .. acc_5
        "*,-3,-7" → все кроме acc_3, acc_7
        "1-5,-3"  → acc_1, acc_2, acc_4, acc_5
    """
    raw = raw.strip()
    if not raw:
        return list(defaults)

    includes = set()
    excludes = set()
    use_all = False

    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        if part == "*":
            use_all = True
        elif part.startswith("-") and len(part) > 1:
            try:
                excludes.add(f"acc_{int(part[1:])}")
            except ValueError:
                pass
        elif "-" in part and not part.startswith("-"):
            try:
                a, b = part.split("-", 1)
                for i in range(int(a), int(b) + 1):
                    includes.add(f"acc_{i}")
            except ValueError:
                pass
        else:
            try:
                includes.add(f"acc_{int(part)}")
            except ValueError:
                pass

    base = set(defaults) if (use_all or not includes) else includes
    result = base - excludes
    return sorted(result, key=lambda x: int(x.split("_")[1]))
