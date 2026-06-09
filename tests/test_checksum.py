from tanuki_pii.recognizers.checksum import (
    validate_corporate_number,
    validate_my_number,
)


def test_my_number_valid():
    # 123456789018 は検査数字(末尾8)が有効。
    assert validate_my_number("123456789018") is True


def test_my_number_invalid():
    assert validate_my_number("123456789012") is False
    assert validate_my_number("000000000000") is True  # remainder<=1 → 0
    assert validate_my_number("12345") is False


def test_corporate_number_roundtrip():
    # 法人番号は先頭が検査数字。任意の下位12桁から検査数字を計算して検証。
    body = "234567890123"  # 12桁
    digits = [int(c) for c in body]
    total = 0
    for n in range(1, 13):
        p_n = digits[12 - n]
        q_n = 1 if n % 2 == 1 else 2
        total += p_n * q_n
    check = 9 - (total % 9)
    full = f"{check}{body}"
    assert validate_corporate_number(full) is True
    # 検査数字を1つずらすと不正。
    bad = f"{(check + 1) % 10}{body}"
    assert validate_corporate_number(bad) is False
