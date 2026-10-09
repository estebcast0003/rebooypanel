def format_compact_number(num: int | float) -> str:
    """Formats numbers into compact human-readable strings: 121232240 -> '121.2M', 5420 -> '5.4K', 850 -> '850'."""
    try:
        num = float(num)
    except (ValueError, TypeError):
        return "0"

    if num < 1_000:
        return f"{int(num)}"
    elif num < 1_000_000:
        val = num / 1_000
        return f"{val:.1f}K".replace(".0K", "K")
    elif num < 1_000_000_000:
        val = num / 1_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    else:
        val = num / 1_000_000_000
        return f"{val:.1f}B".replace(".0B", "B")
