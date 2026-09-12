import hashlib
import hmac

from autocpna.ingestion._coupang_auth import generate_hmac_signature


def test_signature_message_includes_query_string():
    """서명 대상 메시지에 쿼리스트링이 빠지면 실제 API가 401을 반환하므로
    쿼리스트링을 포함한 path로 서명했을 때만 검증에 성공해야 한다."""
    secret_key = "test-secret"
    access_key = "test-access"
    signed_date = "250101T000000Z"
    path_with_query = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search?keyword=foo&limit=5"

    header = generate_hmac_signature("GET", path_with_query, secret_key, access_key, signed_date)

    expected_message = signed_date + "GET" + path_with_query
    expected_signature = hmac.new(
        secret_key.encode("utf-8"), expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    assert f"signature={expected_signature}" in header
    assert f"access-key={access_key}" in header
    assert f"signed-date={signed_date}" in header
