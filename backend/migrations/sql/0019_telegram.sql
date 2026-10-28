-- 2 bosqichli kirish: Google Authenticator (TOTP) o'rniga Telegram orqali kod (foydalanuvchi talabi 2026-10-17).
-- TOTP hech kimda yoqilmagan edi — ustunlar olib tashlanadi.
ALTER TABLE app_user DROP CONSTRAINT app_user_totp_check, DROP COLUMN totp_enabled_at, DROP COLUMN totp_secret_enc;

ALTER TABLE app_user ADD COLUMN telegram_chat_id bigint UNIQUE, ADD COLUMN telegram_name text,
    ADD COLUMN telegram_linked_at timestamptz,
    ADD CONSTRAINT app_user_telegram_check CHECK ((telegram_chat_id IS NULL) = (telegram_linked_at IS NULL));

-- Bir martalik kodlar: link — Telegram'ni ulash (bot /start orqali), login — kirish kodi, unlink — uzish kodi.
-- Kodning o'zi saqlanmaydi, faqat HMAC (SECRET_KEY bilan).
CREATE TABLE telegram_code (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    purpose     text NOT NULL CHECK (purpose IN ('link', 'login', 'unlink')),
    code_hash   char(64) NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    attempts    integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    used_at     timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX ix_telegram_code_user ON telegram_code (user_id, purpose, created_at DESC) WHERE used_at IS NULL;
CREATE INDEX ix_telegram_code_hash ON telegram_code (code_hash) WHERE used_at IS NULL;
