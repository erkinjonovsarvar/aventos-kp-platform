-- 0010: bo'shatilgan KP raqamlari (2026-10-15). O'chirilgan KP raqami odatda qayta berilmaydi (mijozga yuborilgan
-- bo'lishi mumkin). Admin sinov KP lari kabi raqamlarni ataylab bo'shatishi mumkin — shu jadvalga yoziladi.
CREATE TABLE kp_number_release (
    kp_number    bigint PRIMARY KEY,
    reason       text NOT NULL,
    released_by  bigint NOT NULL REFERENCES app_user(id),
    released_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON kp_number_release FOR EACH ROW EXECUTE FUNCTION trg_audit();
