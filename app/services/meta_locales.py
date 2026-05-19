"""
Lista de locales (idiomas) que Meta soporta en targeting / asset_feed_spec.
Formato: (id_numerico, codigo_meta, nombre_legible_es)

El `id` es el que va en `targeting.locales` y en `customization_spec.locales`.
El `code` es el que va en `adlabels` (ej: en_XX, fr_FR).
"""

META_LOCALES = [
    (6,  "en_XX", "Inglés (US)"),
    (24, "en_GB", "Inglés (Reino Unido)"),
    (5,  "es_LA", "Español (Latinoamérica)"),
    (23, "es_ES", "Español (España)"),
    (3,  "es_MX", "Español (México)"),
    (9,  "fr_FR", "Francés"),
    (44, "fr_CA", "Francés (Canadá)"),
    (17, "ru_RU", "Ruso"),
    (11, "ja_JP", "Japonés"),
    (70, "ja_KS", "Japonés (Kansai)"),
    (28, "ar_AR", "Árabe"),
    (10, "de_DE", "Alemán"),
    (16, "it_IT", "Italiano"),
    (4,  "pt_BR", "Portugués (Brasil)"),
    (15, "pt_PT", "Portugués (Portugal)"),
    (19, "tr_TR", "Turco"),
    (12, "ko_KR", "Coreano"),
    (8,  "zh_CN", "Chino (simplificado)"),
    (31, "zh_TW", "Chino (tradicional)"),
    (32, "zh_HK", "Chino (Hong Kong)"),
    (13, "nl_NL", "Holandés"),
    (40, "nl_BE", "Holandés (Bélgica)"),
    (21, "pl_PL", "Polaco"),
    (22, "sv_SE", "Sueco"),
    (29, "no_NO", "Noruego"),
    (30, "da_DK", "Danés"),
    (18, "fi_FI", "Finlandés"),
    (33, "cs_CZ", "Checo"),
    (36, "hu_HU", "Húngaro"),
    (37, "el_GR", "Griego"),
    (45, "ro_RO", "Rumano"),
    (46, "he_IL", "Hebreo"),
    (47, "id_ID", "Indonesio"),
    (48, "vi_VN", "Vietnamita"),
    (49, "th_TH", "Tailandés"),
    (50, "hi_IN", "Hindi"),
    (52, "uk_UA", "Ucraniano"),
    (53, "ms_MY", "Malayo"),
    (54, "fil_PH", "Filipino"),
    (55, "sk_SK", "Eslovaco"),
    (56, "bg_BG", "Búlgaro"),
    (57, "hr_HR", "Croata"),
    (58, "sr_RS", "Serbio"),
    (59, "sl_SI", "Esloveno"),
    (60, "lv_LV", "Letón"),
    (61, "lt_LT", "Lituano"),
    (62, "et_EE", "Estonio"),
    (63, "ca_ES", "Catalán"),
    (64, "eu_ES", "Vasco"),
    (65, "gl_ES", "Gallego"),
    (66, "is_IS", "Islandés"),
    (67, "mk_MK", "Macedonio"),
    (68, "sw_KE", "Suajili"),
    (69, "af_ZA", "Afrikáans"),
    (71, "bn_IN", "Bengalí"),
    (72, "ta_IN", "Tamil"),
    (73, "te_IN", "Telugu"),
    (74, "mr_IN", "Maratí"),
    (75, "ur_PK", "Urdu"),
    (76, "fa_IR", "Persa"),
]


def locale_by_id(locale_id: int):
    for lid, code, name in META_LOCALES:
        if lid == locale_id:
            return {"id": lid, "code": code, "name": name}
    return None


def locale_by_code(code: str):
    for lid, c, name in META_LOCALES:
        if c == code:
            return {"id": lid, "code": c, "name": name}
    return None
