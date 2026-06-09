"""日本語の番号体系のチェックディジット検証。"""


def _digits(text: str):
    return [int(c) for c in text if c.isdigit()]


def validate_my_number(text: str) -> bool:
    """個人番号（マイナンバー, 12桁）のチェックディジット検証。

    下位11桁を P_1..P_11（P_1 が最下位）とし、
    Q_n = n+1 (1<=n<=6), n-5 (7<=n<=11)。
    remainder = (Σ P_n*Q_n) mod 11。
    検査数字 = 0 (remainder<=1) または 11-remainder。
    """
    digits = _digits(text)
    if len(digits) != 12:
        return False
    check = digits[-1]
    body = digits[:-1]  # 上位→下位の順（11桁）
    total = 0
    for n in range(1, 12):
        p_n = body[11 - n]  # P_1 は最下位
        q_n = n + 1 if n <= 6 else n - 5
        total += p_n * q_n
    remainder = total % 11
    expected = 0 if remainder <= 1 else 11 - remainder
    return check == expected


def validate_corporate_number(text: str) -> bool:
    """法人番号（13桁）のチェックディジット検証。

    検査数字は最上位1桁。下位12桁を P_1..P_12（P_1 が最下位）とし、
    Q_n = 1 (n 奇数), 2 (n 偶数)。
    検査数字 = 9 - (Σ P_n*Q_n) mod 9。
    """
    digits = _digits(text)
    if len(digits) != 13:
        return False
    check = digits[0]
    body = digits[1:]  # 下位12桁（上位→下位）
    total = 0
    for n in range(1, 13):
        p_n = body[12 - n]  # P_1 は最下位
        q_n = 1 if n % 2 == 1 else 2
        total += p_n * q_n
    expected = 9 - (total % 9)
    return check == expected
