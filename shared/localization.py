"""Location-aware currency and language support (shared microservice copy).

Mirrors the localization tables used by the ERP monolith so that microservice
responses can expose the same location-aware currency/language block. No
external dependencies: plain data tables and pure functions.

Resolution order used by :func:`resolve_locale`:

1. an explicit ``locale`` (e.g. ``en-US``, ``fr-FR``)
2. an explicit ``country`` (ISO 3166-1 alpha-2, e.g. ``US``, ``FR``)
3. an ``Accept-Language`` header value (first acceptable language)
4. the configured default locale
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

DEFAULT_LOCALE = "en-US"

# `rate` is the amount of currency per 1 USD (indicative static rates).
CURRENCIES: Dict[str, Dict[str, Any]] = {
    "USD": {"name": "US Dollar", "symbol": "$", "decimals": 2, "rate": 1.0, "symbolFirst": True},
    "EUR": {"name": "Euro", "symbol": "\u20ac", "decimals": 2, "rate": 0.92, "symbolFirst": False},
    "GBP": {"name": "British Pound", "symbol": "\u00a3", "decimals": 2, "rate": 0.79, "symbolFirst": True},
    "JPY": {"name": "Japanese Yen", "symbol": "\u00a5", "decimals": 0, "rate": 149.5, "symbolFirst": True},
    "CAD": {"name": "Canadian Dollar", "symbol": "CA$", "decimals": 2, "rate": 1.36, "symbolFirst": True},
    "AUD": {"name": "Australian Dollar", "symbol": "A$", "decimals": 2, "rate": 1.52, "symbolFirst": True},
    "INR": {"name": "Indian Rupee", "symbol": "\u20b9", "decimals": 2, "rate": 83.2, "symbolFirst": True},
    "BRL": {"name": "Brazilian Real", "symbol": "R$", "decimals": 2, "rate": 4.97, "symbolFirst": True},
    "CNY": {"name": "Chinese Yuan", "symbol": "\u00a5", "decimals": 2, "rate": 7.24, "symbolFirst": True},
    "MXN": {"name": "Mexican Peso", "symbol": "MX$", "decimals": 2, "rate": 17.1, "symbolFirst": True},
}

LANGUAGES: Dict[str, Dict[str, str]] = {
    "en": {"name": "English", "nativeName": "English"},
    "fr": {"name": "French", "nativeName": "Fran\u00e7ais"},
    "de": {"name": "German", "nativeName": "Deutsch"},
    "es": {"name": "Spanish", "nativeName": "Espa\u00f1ol"},
    "pt": {"name": "Portuguese", "nativeName": "Portugu\u00eas"},
    "ja": {"name": "Japanese", "nativeName": "\u65e5\u672c\u8a9e"},
    "zh": {"name": "Chinese", "nativeName": "\u4e2d\u6587"},
    "hi": {"name": "Hindi", "nativeName": "\u0939\u093f\u0928\u094d\u0926\u0940"},
}

LOCALES: Dict[str, Dict[str, str]] = {
    "en-US": {"country": "US", "language": "en", "currency": "USD", "name": "English (United States)"},
    "en-GB": {"country": "GB", "language": "en", "currency": "GBP", "name": "English (United Kingdom)"},
    "en-CA": {"country": "CA", "language": "en", "currency": "CAD", "name": "English (Canada)"},
    "en-AU": {"country": "AU", "language": "en", "currency": "AUD", "name": "English (Australia)"},
    "en-IN": {"country": "IN", "language": "en", "currency": "INR", "name": "English (India)"},
    "fr-FR": {"country": "FR", "language": "fr", "currency": "EUR", "name": "French (France)"},
    "fr-CA": {"country": "CA", "language": "fr", "currency": "CAD", "name": "French (Canada)"},
    "de-DE": {"country": "DE", "language": "de", "currency": "EUR", "name": "German (Germany)"},
    "es-ES": {"country": "ES", "language": "es", "currency": "EUR", "name": "Spanish (Spain)"},
    "es-MX": {"country": "MX", "language": "es", "currency": "MXN", "name": "Spanish (Mexico)"},
    "pt-BR": {"country": "BR", "language": "pt", "currency": "BRL", "name": "Portuguese (Brazil)"},
    "ja-JP": {"country": "JP", "language": "ja", "currency": "JPY", "name": "Japanese (Japan)"},
    "zh-CN": {"country": "CN", "language": "zh", "currency": "CNY", "name": "Chinese (China)"},
    "hi-IN": {"country": "IN", "language": "hi", "currency": "INR", "name": "Hindi (India)"},
}

COUNTRY_DEFAULT_LOCALE: Dict[str, str] = {}
for _code, _info in LOCALES.items():
    COUNTRY_DEFAULT_LOCALE.setdefault(_info["country"], _code)


def _to_float(value) -> float:
    return float(value) if value is not None else 0.0


def _normalize_locale(value: str) -> Optional[str]:
    if not value:
        return None
    token = value.strip().replace("_", "-")
    if not token:
        return None
    parts = token.split("-")
    lang = parts[0].lower()
    if len(parts) >= 2:
        candidate = f"{lang}-{parts[1].upper()}"
        if candidate in LOCALES:
            return candidate
    for code, info in LOCALES.items():
        if info["language"] == lang:
            return code
    return None


def _parse_accept_language(header: str) -> List[str]:
    if not header:
        return []
    weighted = []
    for part in header.split(","):
        segment = part.strip()
        if not segment:
            continue
        lang, _, params = segment.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        lang = lang.strip()
        if lang and lang != "*":
            weighted.append((quality, lang))
    weighted.sort(key=lambda item: item[0], reverse=True)
    return [lang for _, lang in weighted]


def resolve_locale(
    locale: Optional[str] = None,
    country: Optional[str] = None,
    accept_language: Optional[str] = None,
    default: str = DEFAULT_LOCALE,
) -> str:
    """Resolve a supported locale from the available signals."""
    if locale:
        normalized = _normalize_locale(locale)
        if normalized:
            return normalized
    if country:
        code = country.strip().upper()
        if code in COUNTRY_DEFAULT_LOCALE:
            return COUNTRY_DEFAULT_LOCALE[code]
    if accept_language:
        for candidate in _parse_accept_language(accept_language):
            normalized = _normalize_locale(candidate)
            if normalized:
                return normalized
    return default if default in LOCALES else DEFAULT_LOCALE


def currency_for_locale(locale: str) -> str:
    return LOCALES.get(locale, LOCALES[DEFAULT_LOCALE])["currency"]


def language_for_locale(locale: str) -> str:
    return LOCALES.get(locale, LOCALES[DEFAULT_LOCALE])["language"]


def locale_info(locale: str) -> Dict[str, Any]:
    code = locale if locale in LOCALES else DEFAULT_LOCALE
    info = LOCALES[code]
    return {
        "locale": code,
        "name": info["name"],
        "country": info["country"],
        "language": {"code": info["language"], **LANGUAGES.get(info["language"], {})},
        "currency": {"code": info["currency"], **CURRENCIES.get(info["currency"], {})},
    }


def convert_amount(amount: float, to_currency: str, from_currency: str = "USD") -> float:
    amount = _to_float(amount)
    src = CURRENCIES.get(from_currency, CURRENCIES["USD"])
    dst = CURRENCIES.get(to_currency, CURRENCIES["USD"])
    usd_value = Decimal(str(amount)) / Decimal(str(src["rate"]))
    converted = usd_value * Decimal(str(dst["rate"]))
    quant = Decimal(1).scaleb(-dst["decimals"])
    return float(converted.quantize(quant, rounding=ROUND_HALF_UP))


def format_money(amount: float, currency: str) -> str:
    meta = CURRENCIES.get(currency, CURRENCIES["USD"])
    decimals = meta["decimals"]
    quant = Decimal(1).scaleb(-decimals)
    value = Decimal(str(_to_float(amount))).quantize(quant, rounding=ROUND_HALF_UP)
    formatted = f"{value:,.{decimals}f}"
    symbol = meta["symbol"]
    if meta.get("symbolFirst", True):
        return f"{symbol}{formatted}"
    return f"{formatted}\u00a0{symbol}"


def supported_locales() -> List[Dict[str, Any]]:
    return [locale_info(code) for code in LOCALES]


def supported_currencies() -> List[Dict[str, Any]]:
    return [{"code": code, **meta} for code, meta in CURRENCIES.items()]


def supported_languages() -> List[Dict[str, Any]]:
    return [{"code": code, **meta} for code, meta in LANGUAGES.items()]


def resolve_locale_from_request(request, default: str = DEFAULT_LOCALE) -> str:
    """Resolve a locale from a Flask request's query args and headers."""
    return resolve_locale(
        locale=request.args.get("locale"),
        country=request.args.get("country"),
        accept_language=request.headers.get("Accept-Language"),
        default=default,
    )


def localize_record(record: Dict[str, Any], money_fields: List[str], locale: str) -> Dict[str, Any]:
    """Return a copy of ``record`` with an added ``localization`` block.

    ``money_fields`` names the keys in ``record`` holding base (USD) amounts.
    The block carries the resolved locale, currency and per-field converted +
    formatted values. The original fields are left untouched for compatibility.
    """
    if not isinstance(record, dict):
        return record
    info = locale_info(locale)
    currency = info["currency"]["code"]
    amounts = {}
    for field in money_fields:
        if field in record and isinstance(record[field], (int, float)):
            base = _to_float(record[field])
            converted = convert_amount(base, currency)
            amounts[field] = {
                "amount": base,
                "convertedAmount": converted,
                "formatted": format_money(converted, currency),
            }
    result = dict(record)
    result["localization"] = {
        "locale": info["locale"],
        "language": info["language"]["code"],
        "currency": currency,
        "amounts": amounts,
    }
    return result
