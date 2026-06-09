"""置換値ジェネレータ（placeholder / synthetic）。

公式 do_sanitize_pii 内のジェネレータを再現:
- placeholder: "PLACEHOLDER{n}"（カウンタはリクエスト内継続）
- synthetic: Faker（locale map 経由）。生成器が無いエンティティは "#####"
- custom: "CUSTOM{n}"
"""

import itertools

from faker import Faker

from .lang import faker_locale
from .mappings import PASSWORD_REPLACEMENT

DEFAULT_SYNTHETIC = "#####"


class _SafeFaker:
    """属性が無ければ default を返す Faker ラッパ（公式 SafeFakerWrapper 相当）。"""

    def __init__(self, faker_instance):
        self._faker = faker_instance

    def __getattr__(self, name):
        if hasattr(self._faker, name):
            return getattr(self._faker, name)
        return lambda: DEFAULT_SYNTHETIC


class RequestCounters:
    """リクエスト単位の placeholder/custom カウンタ（公式互換でリクエスト内継続）。"""

    def __init__(self):
        self.custom = itertools.count(1)
        self.placeholder = itertools.count(1)


class RedactGenerator:
    """置換値ジェネレータ。

    placeholder/custom のカウンタは **リクエスト単位**（公式互換）。message ごとに
    本クラスを作り直しても、カウンタ(RequestCounters)を共有すれば採番が継続する。
    Faker は message の言語に合わせるため message ごとに作ってよい。
    redact_map（original→redact のキャッシュ）は呼び出し側が message ごとに持つ。
    """

    def __init__(self, redact_type: str, language: str, counters: "RequestCounters"):
        self.redact_type = redact_type
        self.language = language
        self._custom_counter = counters.custom
        self._placeholder_counter = counters.placeholder
        if redact_type == "synthetic":
            self._fake = _SafeFaker(Faker([faker_locale(language)]))
        else:
            self._fake = None

    def _custom_gen(self):
        return f"CUSTOM{next(self._custom_counter)}"

    def _placeholder_gen(self, _entity_type):
        return f"PLACEHOLDER{next(self._placeholder_counter)}"

    def _faker_gen(self, entity_type):
        fake = self._fake
        fake_map = {
            "PERSON": fake.name,
            "LOCATION": fake.city,
            "ORGANIZATION": fake.company,
            "PHONE_NUMBER": fake.phone_number,
            "EMAIL_ADDRESS": fake.email,
            "CITY": fake.city,
            "NRP": fake.country,
            "CREDIT_CARD": fake.credit_card_number,
            "DATE_TIME": lambda: fake.date_time().strftime("%Y-%m-%d %H:%M:%S"),
            "IP_ADDRESS": fake.ipv4,
            "US_SSN": fake.ssn,
            "URL": fake.url,
            "DOMAIN_NAME": fake.safe_domain_name,
            "CUSTOM": self._custom_gen,
            "PASSWORD": lambda: PASSWORD_REPLACEMENT,
            # 日本語固有
            "JP_POSTAL_CODE": fake.postcode,
            "JP_ADDRESS": fake.address,
        }
        fn = fake_map.get(entity_type) or (lambda: DEFAULT_SYNTHETIC)
        return fn()

    def generate(self, entity_type: str) -> str:
        if self.redact_type == "synthetic":
            return self._faker_gen(entity_type)
        return self._placeholder_gen(entity_type)
