"""Auth re-exports for backwards compatibility.

Actual implementation lives in app.core.security.
"""
from app.core.security import get_current_user, verify_password, create_access_token  # noqa: F401

# NOTE: 과거의 require_role()은 user.get("role")을 호출했는데 User 모델엔 .get이 없어 호출 즉시 500나는
# 죽은 footgun이었다(어디서도 실사용 안 됨). 역할 가드는 app.core.security.RequireRole 사용.
