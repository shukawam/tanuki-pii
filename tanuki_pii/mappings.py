"""エンティティ⇄カテゴリのマッピングと定数。

公式 ai-pii-service の server.py（ANONYMIZE_MAP / DEFAULT_MODEL_TO_PRESIDIO_ENTITY_MAPPING）
をベースに、日本語固有エンティティ(JP_*)を追記している。

カテゴリ（Kong の `anonymize` キー）は公式の集合から増やさない方針:
- 郵便番号(JP_POSTAL_CODE)・住所(JP_ADDRESS)は entity_type を保持しつつ、
  逆引きでは `general` に集約する（LOCATION に潰さない）。
"""

# --- 定数（公式互換） ---
REDACT_TYPES = ["synthetic", "placeholder"]
PASSWORD_ENTITY = "PASSWORD"
MASKED_CHAR_PASSWORD = "#"
MASK_LENGTH = 8
PASSWORD_REPLACEMENT = MASKED_CHAR_PASSWORD * MASK_LENGTH
CUSTOM_ENTITY = "CUSTOM"

# 日本語固有エンティティ
JP_MY_NUMBER = "JP_MY_NUMBER"
JP_CORPORATE_NUMBER = "JP_CORPORATE_NUMBER"
JP_POSTAL_CODE = "JP_POSTAL_CODE"
JP_ADDRESS = "JP_ADDRESS"
JP_DRIVERS_LICENSE = "JP_DRIVERS_LICENSE"
JP_HEALTH_INSURANCE = "JP_HEALTH_INSURANCE"
JP_PASSPORT = "JP_PASSPORT"
JP_BANK_ACCOUNT = "JP_BANK_ACCOUNT"
JP_DATE_WAREKI = "JP_DATE_WAREKI"

# 公式 server.py の DEFAULT_MODEL_TO_PRESIDIO_ENTITY_MAPPING を踏襲。
# NLP設定YAMLに model_to_presidio_entity_mapping が無い場合のフォールバック。
DEFAULT_MODEL_TO_PRESIDIO_ENTITY_MAPPING = dict(
    PER="PERSON",
    PERSON="PERSON",
    LOC="LOCATION",
    LOCATION="LOCATION",
    GPE="LOCATION",
    ORG="ORGANIZATION",
    DATE="DATE_TIME",
    TIME="DATE_TIME",
    NORP="NRP",
    AGE="AGE",
    ID="ID",
    EMAIL="EMAIL",
    PATIENT="PERSON",
    STAFF="PERSON",
    HOSP="ORGANIZATION",
    PATORG="ORGANIZATION",
    PHONE="PHONE_NUMBER",
    HCW="PERSON",
    HOSPITAL="ORGANIZATION",
    # Korean model compat
    PS="PERSON",
    LC="LOCATION",
    OG="ORGANIZATION",
)

# anonymize カテゴリ → Presidio エンティティ型のリスト。
# 公式 ANONYMIZE_MAP を踏襲し、JP_* を該当キーへ追記。
ANONYMIZE_MAP = {
    "general": ["PERSON", "LOCATION", "ORGANIZATION", JP_POSTAL_CODE, JP_ADDRESS],
    "phone": ["PHONE_NUMBER"],
    "email": ["EMAIL_ADDRESS"],
    "creditcard": ["CREDIT_CARD"],
    "crypto": ["CRYPTO"],
    "date": ["DATE_TIME", JP_DATE_WAREKI],
    "ip": ["IP_ADDRESS"],
    "nrp": ["NRP"],
    "ssn": ["US_SSN", "US_ITIN", "ES_NIF", "AU_ABN", "AU_ACN", "AU_TFN", "IN_PAN"],
    "url": ["URL"],
    "medical": ["MEDICAL_LICENSE", "UK_NHS", "AU_MEDICARE", JP_HEALTH_INSURANCE],
    "driverlicense": [
        "DRIVER_LICENSE",
        "IT_DRIVER_LICENSE",
        "IN_VEHICLE_REGISTRATION",
        JP_DRIVERS_LICENSE,
    ],
    "passport": ["US_PASSPORT", JP_PASSPORT],
    "bank": ["US_BANK_NUMBER", "IT_VAT_CODE", "IBAN_CODE", JP_BANK_ACCOUNT],
    "nationalid": [
        "NATIONAL_ID",
        "ES_NIE",
        "IT_FISCAL_CODE",
        "IT_IDENTITY_CARD",
        "PL_PESEL",
        "SG_NRIC_FIN",
        "SG_UEN",
        "IN_AADHAAR",
        "IN_VOTER",
        "FI_PERSONAL_IDENTITY_CODE",
        JP_MY_NUMBER,
        JP_CORPORATE_NUMBER,
    ],
    "custom": [CUSTOM_ENTITY],
    "credentials": [PASSWORD_ENTITY],
}

# 全エンティティ（重複排除）。公式 ALL_ANONYMIZERS / ALL_WITHOUT_CREDENTIAL に対応。
ALL_ANONYMIZERS = list(
    {entity for entities in ANONYMIZE_MAP.values() for entity in entities}
)
ALL_WITHOUT_CREDENTIAL = list(
    {
        entity
        for entities in ANONYMIZE_MAP.values()
        for entity in entities
        if entity != PASSWORD_ENTITY
    }
)

# 本サービスが Presidio に渡す対応言語。
SUPPORTED_LANGS = {"ja", "en"}

# NER（spaCy/BERT）由来のエンティティ。言語検出失敗時(#3b)はこれらをスキップする。
NER_ENTITIES = {"PERSON", "LOCATION", "ORGANIZATION", "NRP", "DATE_TIME"}

# 正規表現/パターン由来（言語非依存）のエンティティ。#3b で常時実行する対象。
STRUCTURED_REGEX_ENTITIES = [
    e for e in ALL_ANONYMIZERS if e not in NER_ENTITIES and e != PASSWORD_ENTITY
]


def get_sorted_anonymize_keys(entity_types):
    """エンティティ型の集合 → 対応する anonymize カテゴリキー（アルファベット順）。

    公式 get_sorted_anonymize_keys と同一仕様。1つのエンティティが複数カテゴリに
    属する場合は全カテゴリを返す。
    """
    result = set()
    for key, mapped_values in ANONYMIZE_MAP.items():
        for value in entity_types:
            if value in mapped_values:
                result.add(key)
    return sorted(result)


def get_entities_to_anonymize(anonymize):
    """anonymize 指定 → Presidio エンティティ型リスト。

    公式 get_entities_to_anonymize と同一仕様:
    - list でなければ TypeError
    - "all_and_credentials" → 全部
    - "all" → credentials 以外全部
    - 未知カテゴリ → TypeError（= 400）。`domain` もここで弾かれる。
    """
    if not isinstance(anonymize, list):
        raise TypeError("No valid `anonymize` found")

    if "all_and_credentials" in anonymize:
        return list(ALL_ANONYMIZERS)

    if "all" in anonymize:
        return list(ALL_WITHOUT_CREDENTIAL)

    # domain は公式では未知カテゴリ(=400)。ENABLE_DOMAIN_ALIAS 有効時のみ url 別名として受理。
    from .config import settings

    entities_to_anonymize = []
    for entity in anonymize:
        if not isinstance(entity, str):
            raise TypeError(f"Invalid type of item found in `anonymize`: {entity}")
        entity = entity.lower()
        if entity in ANONYMIZE_MAP:
            entities_to_anonymize.extend(ANONYMIZE_MAP[entity])
        elif entity == "domain" and settings.enable_domain_alias:
            entities_to_anonymize.extend(ANONYMIZE_MAP["url"])
        else:
            raise TypeError(f"Invalid item found in `anonymize`: {entity}")

    return entities_to_anonymize
