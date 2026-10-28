-- 0017: xavfsizlik (foydalanuvchi tasdiqlagan audit, 2026-10-17 — SECURITY_AUDIT_2026-10-17.md, 1–11).
--  * user_session — sessiyalar bazada: "Chiqish" bekor qiladi, harakatsizlik va muddat bo'yicha tugaydi, admin hammasini bekor qila oladi.
--    Cookie da faqat tasodifiy token, bazada uning SHA-256 hash'i.
--  * auth_event — xavfsizlik jurnali (faqat qo'shiladi): kirish urinishlari, bloklash, 2FA, sessiya bekor qilish, taklif havolasi urinishlari.
--    Parol taxmin qilishdan himoya shu jurnal asosida (server qayta yonsa ham saqlanadi).
--  * app_user.totp_* — 2 bosqichli kirish (telefon ilovasi kodi); maxfiy kalit shifrlangan holda.

CREATE TABLE user_session (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    token_hash      char(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    revoked_reason  text,
    ip              text,
    user_agent      text,
    CHECK (expires_at > created_at),
    CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);
CREATE INDEX ix_user_session_user ON user_session (user_id) WHERE revoked_at IS NULL;

CREATE TABLE auth_event (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    event       text NOT NULL CHECK (event IN (
                    'login_ok', 'login_failed', 'login_locked', 'ip_blocked', 'mfa_required', 'mfa_failed',
                    'logout', 'session_expired', 'sessions_revoked',
                    'mfa_enabled', 'mfa_disabled', 'mfa_reset',
                    'join_invalid', 'join_submitted', 'join_blocked')),
    login       text,
    user_id     bigint REFERENCES app_user(id) ON DELETE SET NULL,
    ip          text,
    user_agent  text,
    details     text
);
CREATE INDEX ix_auth_event_login ON auth_event (lower(login), at DESC);
CREATE INDEX ix_auth_event_ip ON auth_event (ip, at DESC);
CREATE INDEX ix_auth_event_at ON auth_event (at DESC);
-- jurnal o'zgarmaydi (foydalanuvchi o'chirilganda user_id NULL bo'lishi — ON DELETE SET NULL — bundan mustasno)
CREATE FUNCTION trg_auth_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.user_id IS NULL AND OLD.user_id IS NOT NULL
       AND ROW(NEW.at, NEW.event, NEW.login, NEW.ip, NEW.user_agent, NEW.details)
           IS NOT DISTINCT FROM ROW(OLD.at, OLD.event, OLD.login, OLD.ip, OLD.user_agent, OLD.details) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION USING MESSAGE = 'Xavfsizlik jurnali faqat qo''shiladi: ' || TG_OP || ' taqiqlangan', ERRCODE = 'P0001';
END $$;
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON auth_event FOR EACH ROW EXECUTE FUNCTION trg_auth_event_append_only();

ALTER TABLE app_user ADD COLUMN totp_secret_enc text, ADD COLUMN totp_enabled_at timestamptz,
    ADD CONSTRAINT app_user_totp_check CHECK (totp_enabled_at IS NULL OR totp_secret_enc IS NOT NULL);
