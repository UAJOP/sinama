from app.masking import mask_sensitive_text


def test_masks_tc_kimlik_no() -> None:
    assert mask_sensitive_text("TC kimlik no: 12345678901 kayıtlı.") == (
        "TC kimlik no: 123******01 kayıtlı."
    )


def test_masks_turkish_mobile_phone_keeping_first_three_and_last_four() -> None:
    assert mask_sensitive_text("Telefon numaram 5321234567.") == "Telefon numaram 532***4567."


def test_masks_turkish_mobile_phone_with_country_code_and_separators() -> None:
    assert mask_sensitive_text("Telefon numaram +90 532 123 45 67.") == (
        "Telefon numaram 532***4567."
    )


def test_masks_card_like_digit_run() -> None:
    assert mask_sensitive_text("Kart no 4111 1111 1111 1111 ile odedi.") == (
        "Kart no 4111********1111 ile odedi."
    )


def test_leaves_non_sensitive_alphanumeric_ids_untouched() -> None:
    text = "Poliçe numaranız POL-DEMO-1001 olarak kaydedildi."
    assert mask_sensitive_text(text) == text


def test_leaves_short_digit_runs_untouched() -> None:
    text = "Hasar dosyası CLM-DEMO-0001 numarasıyla oluşturuldu."
    assert mask_sensitive_text(text) == text
