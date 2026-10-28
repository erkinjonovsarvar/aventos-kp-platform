-- Taklif havolasini admin bekor qila oladi (UX audit 2026-10-17).
ALTER TABLE invitation ADD COLUMN revoked_at timestamptz;
