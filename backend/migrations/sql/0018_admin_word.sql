-- Admin paneli uchun maxfiy so'z (foydalanuvchi talabi 2026-10-17): faqat admin o'zi biladi, bazada Argon2 hash.
-- Sessiyada admin paneli ochilgan vaqt (harakatsizlikdan keyin so'z qayta so'raladi).
ALTER TABLE app_user ADD COLUMN admin_word_hash text, ADD COLUMN admin_word_set_at timestamptz;
ALTER TABLE user_session ADD COLUMN admin_unlocked_at timestamptz;

ALTER TABLE auth_event DROP CONSTRAINT auth_event_event_check;
ALTER TABLE auth_event ADD CONSTRAINT auth_event_event_check CHECK (event IN (
    'login_ok', 'login_failed', 'login_locked', 'ip_blocked', 'mfa_required', 'mfa_failed',
    'logout', 'session_expired', 'sessions_revoked',
    'mfa_enabled', 'mfa_disabled', 'mfa_reset',
    'join_invalid', 'join_submitted', 'join_blocked',
    'admin_word_set', 'admin_word_ok', 'admin_word_failed', 'admin_word_locked'));
