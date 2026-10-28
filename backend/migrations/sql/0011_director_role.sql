-- 0011: "Direktor" roli (foydalanuvchi qarori 2026-10-15: direktor "admin bilan teng", lekin KP ni o'chirish faqat
-- foydalanuvchining o'zida — kp.delete faqat admin rolida).
INSERT INTO role (code, name) VALUES ('director', 'Direktor (KP o''chirishdan tashqari hammasi)');
INSERT INTO role_permission (role_code, permission_code)
SELECT 'director', code FROM permission WHERE code <> 'kp.delete';
