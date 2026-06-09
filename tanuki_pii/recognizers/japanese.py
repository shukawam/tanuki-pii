"""日本語固有 PII の正規表現 Recognizer。"""

from presidio_analyzer import Pattern, PatternRecognizer

from ..mappings import (
    JP_ADDRESS,
    JP_BANK_ACCOUNT,
    JP_CORPORATE_NUMBER,
    JP_DATE_WAREKI,
    JP_DRIVERS_LICENSE,
    JP_HEALTH_INSURANCE,
    JP_MY_NUMBER,
    JP_PASSPORT,
    JP_POSTAL_CODE,
)
from .checksum import validate_corporate_number, validate_my_number

# 47都道府県。
_PREFECTURES = (
    "北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|"
    "埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|"
    "岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|"
    "鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|"
    "佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県"
)


class _ChecksumRecognizer(PatternRecognizer):
    """チェックディジット検証付き PatternRecognizer。"""

    def __init__(self, validator, **kwargs):
        super().__init__(**kwargs)
        self._validator = validator

    def validate_result(self, pattern_text):
        return self._validator(pattern_text)


def _my_number_recognizer(language):
    patterns = [
        Pattern(
            name="jp_my_number",
            # 12桁（4-4-4 区切り/空白も可）。前後が数字でないこと。
            regex=r"(?<!\d)\d{4}[- ]?\d{4}[- ]?\d{4}(?!\d)",
            score=0.4,
        )
    ]
    return _ChecksumRecognizer(
        validator=validate_my_number,
        supported_entity=JP_MY_NUMBER,
        patterns=patterns,
        context=["マイナンバー", "個人番号", "マイナ"],
        supported_language=language,
        name="JpMyNumberRecognizer",
    )


def _corporate_number_recognizer(language):
    patterns = [
        Pattern(
            name="jp_corporate_number",
            regex=r"(?<!\d)\d{13}(?!\d)",
            score=0.4,
        )
    ]
    return _ChecksumRecognizer(
        validator=validate_corporate_number,
        supported_entity=JP_CORPORATE_NUMBER,
        patterns=patterns,
        context=["法人番号", "会社", "法人"],
        supported_language=language,
        name="JpCorporateNumberRecognizer",
    )


def _phone_recognizer(language):
    patterns = [
        # 携帯
        Pattern(name="jp_mobile", regex=r"(?<![\d-])0[789]0-\d{4}-\d{4}(?![\d-])", score=0.7),
        # フリーダイヤル
        Pattern(name="jp_freedial", regex=r"(?<![\d-])0120-\d{2,3}-\d{3,4}(?![\d-])", score=0.7),
        # 固定（市外局番 2-5 桁 + 局番 + 番号）
        Pattern(name="jp_landline", regex=r"(?<![\d-])0\d{1,4}-\d{1,4}-\d{4}(?![\d-])", score=0.6),
        # 国際表記 +81
        Pattern(name="jp_intl", regex=r"(?<![\d-])\+81[- ]?\d{1,4}[- ]?\d{1,4}[- ]?\d{4}(?![\d-])", score=0.7),
        # 市外局番括弧表記
        Pattern(name="jp_paren", regex=r"(?<![\d-])\(0\d{1,4}\)\d{1,4}-\d{4}(?![\d-])", score=0.6),
    ]
    return PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        patterns=patterns,
        context=["電話", "TEL", "tel", "携帯", "連絡先"],
        supported_language=language,
        name="JpPhoneRecognizer",
    )


def _postal_code_recognizer(language):
    patterns = [
        Pattern(name="jp_postal_marked", regex=r"〒\s?\d{3}-?\d{4}", score=0.6),
        # ハイフン連結の電話番号等に巻き込まれないよう前後のハイフン/数字を除外。
        Pattern(name="jp_postal", regex=r"(?<![\d-])\d{3}-\d{4}(?![\d-])", score=0.3),
    ]
    return PatternRecognizer(
        supported_entity=JP_POSTAL_CODE,
        patterns=patterns,
        context=["〒", "郵便番号", "郵便"],
        supported_language=language,
        name="JpPostalCodeRecognizer",
    )


def _address_recognizer(language):
    # 都道府県 + 市区町村 + 丁目番地（漢数字/算用数字、-区切りも許容）。
    block = r"(?:\d+|[一二三四五六七八九十百]+)"
    chome = rf"{block}丁目{block}番(?:{block}号)?"
    hyphen = r"\d+(?:-\d+){1,2}"
    tail = rf"[^\s、。０-９]{{0,15}}?(?:{chome}|{hyphen})"
    patterns = [
        Pattern(
            name="jp_address",
            regex=rf"(?:{_PREFECTURES})[^\s、。]{{1,20}}?(?:市|区|町|村)[^\s、。]{{0,20}}?(?:{chome}|{hyphen})",
            score=0.6,
        ),
        Pattern(
            name="jp_address_pref_block",
            regex=rf"(?:{_PREFECTURES}){tail}",
            score=0.4,
        ),
    ]
    return PatternRecognizer(
        supported_entity=JP_ADDRESS,
        patterns=patterns,
        context=["住所", "在住", "番地"],
        supported_language=language,
        name="JpAddressRecognizer",
    )


def _drivers_license_recognizer(language):
    patterns = [
        Pattern(name="jp_drivers_license", regex=r"(?<!\d)\d{12}(?!\d)", score=0.3)
    ]
    return PatternRecognizer(
        supported_entity=JP_DRIVERS_LICENSE,
        patterns=patterns,
        context=["免許", "運転免許", "免許証"],
        supported_language=language,
        name="JpDriversLicenseRecognizer",
    )


def _health_insurance_recognizer(language):
    patterns = [
        # 保険者番号8桁 + 記号 + 番号（緩め）。context 必須でスコアを上げる。
        Pattern(name="jp_health_insurance", regex=r"(?<!\d)\d{8}(?!\d)", score=0.2)
    ]
    return PatternRecognizer(
        supported_entity=JP_HEALTH_INSURANCE,
        patterns=patterns,
        context=["保険証", "被保険者", "保険者番号", "健康保険"],
        supported_language=language,
        name="JpHealthInsuranceRecognizer",
    )


def _passport_recognizer(language):
    patterns = [
        Pattern(name="jp_passport", regex=r"(?<![A-Za-z0-9])[A-Z]{2}\d{7}(?![A-Za-z0-9])", score=0.5)
    ]
    return PatternRecognizer(
        supported_entity=JP_PASSPORT,
        patterns=patterns,
        context=["旅券", "パスポート", "passport"],
        supported_language=language,
        name="JpPassportRecognizer",
    )


def _bank_account_recognizer(language):
    patterns = [
        Pattern(name="jp_bank_account", regex=r"(?<!\d)\d{7}(?!\d)", score=0.2)
    ]
    return PatternRecognizer(
        supported_entity=JP_BANK_ACCOUNT,
        patterns=patterns,
        context=["口座", "普通", "当座", "口座番号", "銀行"],
        supported_language=language,
        name="JpBankAccountRecognizer",
    )


def _wareki_date_recognizer(language):
    patterns = [
        Pattern(
            name="jp_wareki",
            regex=r"(令和|平成|昭和|大正|明治)\s?(元|\d{1,2})年\d{1,2}月\d{1,2}日",
            score=0.7,
        ),
        Pattern(
            name="jp_wareki_abbr",
            # R/H/S 等 + 数字。`.` を任意文字にしない。
            regex=r"(?<![A-Za-z0-9])[RHSTM]\d{1,2}[./-]\d{1,2}[./-]\d{1,2}(?![A-Za-z0-9])",
            score=0.4,
        ),
        Pattern(
            name="jp_seireki",
            regex=r"\d{4}年\d{1,2}月\d{1,2}日",
            score=0.6,
        ),
    ]
    # 西暦の年月日は DATE_TIME に寄せる方が公式カテゴリ(date)に自然だが、
    # 和暦は専用エンティティで保持し逆引きで date に集約。
    return PatternRecognizer(
        supported_entity=JP_DATE_WAREKI,
        patterns=patterns,
        context=["日付", "生年月日", "年月日"],
        supported_language=language,
        name="JpWarekiDateRecognizer",
    )


_FACTORIES = [
    _my_number_recognizer,
    _corporate_number_recognizer,
    _phone_recognizer,
    _postal_code_recognizer,
    _address_recognizer,
    _drivers_license_recognizer,
    _health_insurance_recognizer,
    _passport_recognizer,
    _bank_account_recognizer,
    _wareki_date_recognizer,
]


def build_japanese_recognizers(language):
    """指定言語の日本語固有 Recognizer 一覧を生成する。"""
    return [factory(language) for factory in _FACTORIES]
