-- 0008: KP ni o'chirish — alohida ruxsat, faqat admin (foydalanuvchi talabi 2026-10-15:
-- "Tayyorlangan KP larni faqat men o'chira olishim kerak").
INSERT INTO permission (code, name) VALUES ('kp.delete', 'KP ni o''chirish (faqat admin)');
INSERT INTO role_permission (role_code, permission_code) VALUES ('admin', 'kp.delete');
