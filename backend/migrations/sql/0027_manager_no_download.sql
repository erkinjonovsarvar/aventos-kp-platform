-- 0027: Menejer KP ni Excel (PDF) qilib yuklab ola olmaydi — hozircha (foydalanuvchi qarori 2026-10-28:
--   "manager excel yuklab ola olmasligi kerak hozircha kelajakda yuklasa bo'ladigan qilamiz").
-- kp.download menejer rolidan olinadi. Keyin ochish: alohida xodimga — "Foydalanuvchilar" sahifasida qo'shimcha ruxsat
-- (user_permission), hammaga — shu migratsiyaning downgrade'i (rolga qaytariladi). Admin va direktor rollari o'zgarmaydi.
DELETE FROM role_permission WHERE role_code = 'manager' AND permission_code = 'kp.download';
